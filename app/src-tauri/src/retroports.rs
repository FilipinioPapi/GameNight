//! Lists the controllers the way RetroArch sees them, so Game Night can tell it which one is Player 1
//! and which ones to ignore, and works out which of RetroArch's two Windows controller readers to use.
//!
//! RetroArch's "xinput" reader pairs each Xbox-style pad it finds with an XInput slot by counting
//! (input/drivers_joypad/xinput_hybrid_joypad.c in 1.22.2: enum_joypad_cb_hybrid). That goes wrong when
//! Windows has an Xbox-style slot that has no matching device in the list. Jayden's Razer Huntsman has
//! a hidden "Xbox 360 controller" (046d:0000) in slot 1 and his real pad in slot 2, so RetroArch read
//! the dead slot 1 for his pad. When that would happen, Game Night uses RetroArch's "dinput" reader,
//! which reads each device directly. Read-only: it only lists devices.

#[derive(Clone, Debug, PartialEq)]
pub struct Device {
    /// The name Windows gives it, e.g. "Controller (Xbox One For Windows)".
    pub name: String,
    /// RetroArch's id, "vvvv:pppp": what its device reservations match.
    pub ra: (u16, u16),
    /// The id Game Night's menus see for it (the same as `ra` for everything listed here).
    pub usb: (u16, u16),
}

/// What's plugged in, and whether RetroArch's "xinput" reader would read the wrong slot for a pad.
#[derive(Clone, Debug, Default, PartialEq)]
pub struct Scan {
    pub devices: Vec<Device>,
    pub xinput_misreads: bool,
}

/// What RetroArch should use to read controllers for this scan.
pub fn joypad_driver(scan: &Scan) -> &'static str {
    if scan.xinput_misreads {
        "dinput"
    } else {
        "xinput"
    }
}

#[cfg(windows)]
mod imp {
    use super::{Device, Scan};
    use std::ffi::c_void;
    use windows::core::{Interface, BOOL, GUID, PCSTR};
    use windows::Win32::Devices::HumanInterfaceDevice::{
        DirectInput8Create, IDirectInput8W, IDirectInputDevice8W, DI8DEVCLASS_GAMECTRL, DIDEVICEINSTANCEW,
        DIEDFL_ATTACHEDONLY,
    };
    use windows::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress, LoadLibraryW};
    use windows::Win32::UI::Input::XboxController::{XInputGetState, XINPUT_CAPABILITIES, XINPUT_STATE};
    use windows::Win32::UI::Input::{
        GetRawInputDeviceInfoW, GetRawInputDeviceList, RAWINPUTDEVICELIST, RIDI_DEVICEINFO, RIDI_DEVICENAME,
        RID_DEVICE_INFO, RIM_TYPEHID,
    };

    const OK: u32 = 0;

    fn xinput_connected() -> [bool; 4] {
        let mut out = [false; 4];
        for (i, c) in out.iter_mut().enumerate() {
            let mut st = XINPUT_STATE::default();
            *c = unsafe { XInputGetState(i as u32, &mut st) } == OK;
        }
        out
    }

    #[repr(C)]
    #[derive(Default)]
    struct CapabilitiesEx {
        caps: XINPUT_CAPABILITIES,
        vendor_id: u16,
        product_id: u16,
        product_version: u16,
        unk1: u16,
        unk2: u32,
    }
    type GetCapsEx = unsafe extern "system" fn(u32, u32, u32, *mut CapabilitiesEx) -> u32;

    /// The id Windows gives the pad in an XInput slot (0-3), via XInputGetCapabilitiesEx
    /// (xinput1_4.dll ordinal 108), as SDL does. For an Xbox pad it's the same id RetroArch uses.
    pub fn slot_id(slot: u32) -> Option<(u16, u16)> {
        static CAPS_EX: std::sync::OnceLock<Option<GetCapsEx>> = std::sync::OnceLock::new();
        let f = (*CAPS_EX.get_or_init(|| unsafe {
            let dll = LoadLibraryW(windows::core::w!("xinput1_4.dll")).ok()?;
            let f = GetProcAddress(dll, PCSTR(108usize as *const u8))?;
            Some(std::mem::transmute::<_, GetCapsEx>(f))
        }))?;
        let mut c = CapabilitiesEx::default();
        (unsafe { f(1, slot, 0, &mut c) } == OK).then_some((c.vendor_id, c.product_id))
    }

    /// guid_is_xinput_device: well-known Xbox 360 ids, or a HID device whose path has "IG_".
    fn is_xinput(product: &GUID) -> bool {
        const KNOWN: [(u16, u16); 3] = [(0x28DE, 0x11FF), (0x045E, 0x02A1), (0x045E, 0x028E)];
        const PIDVID: [u8; 8] = [0x00, 0x00, 0x50, 0x49, 0x44, 0x56, 0x49, 0x44];
        if product.data2 == 0
            && product.data3 == 0
            && product.data4 == PIDVID
            && KNOWN.iter().any(|&(v, p)| product.data1 == (v as u32) | ((p as u32) << 16))
        {
            return true;
        }
        unsafe {
            let mut count = 0u32;
            let size = std::mem::size_of::<RAWINPUTDEVICELIST>() as u32;
            if GetRawInputDeviceList(None, &mut count, size) == u32::MAX || count == 0 {
                return false;
            }
            let mut list = vec![RAWINPUTDEVICELIST::default(); count as usize];
            if GetRawInputDeviceList(Some(list.as_mut_ptr()), &mut count, size) == u32::MAX {
                return false;
            }
            for d in list.iter().take(count as usize) {
                if d.dwType != RIM_TYPEHID {
                    continue;
                }
                let mut info = RID_DEVICE_INFO { cbSize: std::mem::size_of::<RID_DEVICE_INFO>() as u32, ..Default::default() };
                let mut info_size = info.cbSize;
                if GetRawInputDeviceInfoW(Some(d.hDevice), RIDI_DEVICEINFO, Some(&mut info as *mut _ as *mut c_void), &mut info_size)
                    == u32::MAX
                {
                    continue;
                }
                let hid = info.Anonymous.hid;
                if (hid.dwVendorId & 0xFFFF) | ((hid.dwProductId & 0xFFFF) << 16) != product.data1 {
                    continue;
                }
                let mut len = 0u32;
                if GetRawInputDeviceInfoW(Some(d.hDevice), RIDI_DEVICENAME, None, &mut len) == u32::MAX || len == 0 {
                    continue;
                }
                let mut name = vec![0u16; len as usize];
                if GetRawInputDeviceInfoW(Some(d.hDevice), RIDI_DEVICENAME, Some(name.as_mut_ptr() as *mut c_void), &mut len)
                    == u32::MAX
                {
                    continue;
                }
                if String::from_utf16_lossy(&name).contains("IG_") {
                    return true;
                }
            }
        }
        false
    }

    struct Walk {
        input: Option<IDirectInput8W>,
        connected: [bool; 4],
        next_slot: usize,
        found: Vec<Device>,
        /// Xbox-style devices and the XInput slot RetroArch's "xinput" reader would read for each.
        paired: Vec<((u16, u16), Option<usize>)>,
    }

    unsafe extern "system" fn each(inst: *mut DIDEVICEINSTANCEW, data: *mut c_void) -> BOOL {
        let w = &mut *(data as *mut Walk);
        let inst = &*inst;
        if w.found.len() == 16 {
            return BOOL(0); // RetroArch's MAX_USERS
        }
        while w.next_slot < 3 && !w.connected[w.next_slot] {
            w.next_slot += 1;
        }
        // RetroArch skips a device it can't open.
        let mut dev: Option<IDirectInputDevice8W> = None;
        let Some(input) = &w.input else { return BOOL(0) };
        if input.CreateDevice(&inst.guidInstance, &mut dev, None).is_err() {
            return BOOL(1);
        }
        let id = inst.guidProduct.data1;
        let ra = ((id & 0xFFFF) as u16, (id >> 16) as u16);
        if is_xinput(&inst.guidProduct) {
            let slot = (w.next_slot < 4).then_some(w.next_slot);
            w.next_slot += 1;
            w.paired.push((ra, slot));
        }
        let n = &inst.tszProductName;
        let len = n.iter().position(|&c| c == 0).unwrap_or(n.len());
        let name: String = String::from_utf16_lossy(&n[..len]).trim().chars().take(80).collect();
        w.found.push(Device { name, ra, usb: ra });
        BOOL(1)
    }

    pub fn scan() -> Scan {
        let connected = xinput_connected();
        let slots: Vec<Option<(u16, u16)>> =
            (0..4).map(|i| if connected[i] { slot_id(i as u32) } else { None }).collect();
        let mut walk = Walk { input: None, connected, next_slot: 0, found: vec![], paired: vec![] };
        unsafe {
            if let Ok(module) = GetModuleHandleW(None) {
                let mut raw: *mut c_void = std::ptr::null_mut();
                if DirectInput8Create(module.into(), 0x0800, &IDirectInput8W::IID, &mut raw, None).is_ok() && !raw.is_null() {
                    let input = IDirectInput8W::from_raw(raw);
                    walk.input = Some(input.clone());
                    let _ = input.EnumDevices(
                        DI8DEVCLASS_GAMECTRL,
                        Some(each),
                        &mut walk as *mut Walk as *mut c_void,
                        DIEDFL_ATTACHEDONLY,
                    );
                }
            }
        }
        super::finish(walk.found, &walk.paired, &slots)
    }
}

/// Finishes a scan: adds Xbox-style slots that have no device in RetroArch's list (so they can be
/// seen and turned off in Settings), and checks whether the "xinput" reader would pair any pad with
/// a slot that holds a different controller.
/// `paired`: each Xbox-style device's id and the slot RetroArch would read for it.
/// `slots`: the id in each connected XInput slot (None: empty, or Windows didn't say).
#[cfg_attr(not(windows), allow(dead_code))]
fn finish(mut devices: Vec<Device>, paired: &[((u16, u16), Option<usize>)], slots: &[Option<(u16, u16)>]) -> Scan {
    let xinput_misreads = paired.iter().any(|(ra, slot)| match slot.and_then(|s| slots.get(s).copied().flatten()) {
        Some(there) => there != *ra,
        None => false,
    });
    for id in slots.iter().flatten() {
        if !paired.iter().any(|(ra, _)| ra == id) && !devices.iter().any(|d| d.ra == *id) {
            devices.push(Device { name: "Hidden Xbox-style controller".into(), ra: *id, usb: *id });
        }
    }
    Scan { devices, xinput_misreads }
}

/// Every controller plugged in right now, in RetroArch's order.
#[cfg(windows)]
pub use imp::scan;

#[cfg(not(windows))]
pub fn scan() -> Scan {
    Scan::default()
}

/// The id of the controller in an XInput slot (0-3), if one is there.
#[cfg(windows)]
pub use imp::slot_id;

#[cfg(test)]
mod tests {
    use super::*;

    fn dev(name: &str, ra: (u16, u16)) -> Device {
        Device { name: name.into(), ra, usb: ra }
    }

    const PAD: (u16, u16) = (0x045e, 0x02ff);
    const RAZER: (u16, u16) = (0x1532, 0x02a7);
    const HIDDEN: (u16, u16) = (0x046d, 0x0000);

    #[test]
    fn jaydens_pc_the_hidden_slot_makes_xinput_read_the_wrong_pad() {
        // DirectInput lists the Razer and the pad; XInput slot 1 is the Razer's hidden pad, slot 2 his pad.
        let s = finish(vec![dev("Razer", RAZER), dev("Xbox", PAD)], &[(PAD, Some(0))], &[Some(HIDDEN), Some(PAD), None, None]);
        assert!(s.xinput_misreads);
        assert_eq!(joypad_driver(&s), "dinput");
        assert_eq!(s.devices.len(), 3);
        assert_eq!(s.devices[2].ra, HIDDEN); // shown in Settings so it can be turned off
    }

    #[test]
    fn a_normal_pc_keeps_the_xinput_reader() {
        let s = finish(vec![dev("Xbox", PAD)], &[(PAD, Some(0))], &[Some(PAD), None, None, None]);
        assert!(!s.xinput_misreads);
        assert_eq!(joypad_driver(&s), "xinput");
        assert_eq!(s.devices.len(), 1);
    }

    #[test]
    fn keyboard_unplugged_the_pad_stays_in_slot_2_and_is_read_right() {
        // RetroArch skips empty slots, so the pad is paired with slot 2.
        let s = finish(vec![dev("Xbox", PAD)], &[(PAD, Some(1))], &[None, Some(PAD), None, None]);
        assert!(!s.xinput_misreads);
    }

    #[test]
    fn two_identical_pads_are_fine() {
        let s = finish(vec![dev("Xbox", PAD), dev("Xbox", PAD)], &[(PAD, Some(0)), (PAD, Some(1))], &[Some(PAD), Some(PAD), None, None]);
        assert!(!s.xinput_misreads);
        assert_eq!(s.devices.len(), 2);
    }

    #[test]
    fn unknown_slot_ids_are_not_treated_as_wrong() {
        let s = finish(vec![dev("Xbox", PAD)], &[(PAD, Some(0))], &[None, None, None, None]);
        assert!(!s.xinput_misreads);
    }
}
