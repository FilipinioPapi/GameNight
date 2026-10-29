//! Lists the controllers the way RetroArch (its Windows "xinput" driver) sees them, so Game Night can
//! tell it which one is Player 1 and which ones to ignore. RetroArch names an Xbox-style pad by a
//! different id than Windows' USB id (Jayden's Xbox Series pad: 045e:02ff to RetroArch, 045e:0b12 by
//! USB), so both are worked out here. This repeats RetroArch 1.22.2's own steps
//! (input/drivers_joypad/xinput_hybrid_joypad.c: enum_joypad_cb_hybrid and guid_is_xinput_device).
//! Read-only: it only lists devices.

#[derive(Clone, Debug, PartialEq)]
pub struct Device {
    /// The name Windows gives it, e.g. "Controller (Xbox One For Windows)".
    pub name: String,
    /// RetroArch's id, "vvvv:pppp": what its device reservations match.
    pub ra: (u16, u16),
    /// The USB id Game Night's menus see for it (same as `ra` unless it's an Xbox-style pad).
    pub usb: (u16, u16),
}

#[cfg(windows)]
mod imp {
    use super::Device;
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

    /// The USB id of the pad in an XInput slot, via XInputGetCapabilitiesEx (xinput1_4.dll
    /// ordinal 108), as SDL does.
    fn slot_usb_id(slot: u32) -> Option<(u16, u16)> {
        unsafe {
            let dll = LoadLibraryW(windows::core::w!("xinput1_4.dll")).ok()?;
            let f = GetProcAddress(dll, PCSTR(108usize as *const u8))?;
            let f: GetCapsEx = std::mem::transmute(f);
            let mut c = CapabilitiesEx::default();
            (f(1, slot, 0, &mut c) == OK && c.vendor_id != 0).then_some((c.vendor_id, c.product_id))
        }
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
        input: IDirectInput8W,
        connected: [bool; 4],
        next_slot: usize,
        found: Vec<Device>,
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
        if w.input.CreateDevice(&inst.guidInstance, &mut dev, None).is_err() {
            return BOOL(1);
        }
        let id = inst.guidProduct.data1;
        let ra = ((id & 0xFFFF) as u16, (id >> 16) as u16);
        let mut usb = ra;
        if is_xinput(&inst.guidProduct) && w.next_slot < 4 {
            if let Some(u) = slot_usb_id(w.next_slot as u32) {
                usb = u;
            }
            w.next_slot += 1;
        }
        let n = &inst.tszProductName;
        let len = n.iter().position(|&c| c == 0).unwrap_or(n.len());
        let name: String = String::from_utf16_lossy(&n[..len]).trim().chars().take(80).collect();
        w.found.push(Device { name, ra, usb });
        BOOL(1)
    }

    pub fn devices() -> Vec<Device> {
        unsafe {
            let Ok(module) = GetModuleHandleW(None) else { return vec![] };
            let mut raw: *mut c_void = std::ptr::null_mut();
            if DirectInput8Create(module.into(), 0x0800, &IDirectInput8W::IID, &mut raw, None).is_err() || raw.is_null() {
                return vec![];
            }
            let input = IDirectInput8W::from_raw(raw);
            let mut walk = Walk { input: input.clone(), connected: xinput_connected(), next_slot: 0, found: vec![] };
            let _ = input.EnumDevices(DI8DEVCLASS_GAMECTRL, Some(each), &mut walk as *mut Walk as *mut c_void, DIEDFL_ATTACHEDONLY);
            walk.found
        }
    }
}

/// Every controller plugged in right now, in RetroArch's order.
#[cfg(windows)]
pub use imp::devices;

#[cfg(not(windows))]
pub fn devices() -> Vec<Device> {
    vec![]
}
