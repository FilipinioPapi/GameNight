# The Game Night server: Discord sign-in and the game list, in front of RomM.
# Holds only the Discord login's client secret and a read-only RomM token. No ports to RomM are opened.
FROM python:3.13-slim

ENV VIRTUAL_ENV=/opt/venv PATH=/opt/venv/bin:$PATH
RUN python -m venv /opt/venv
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY gamenight ./gamenight

# Run as Unraid's standard "nobody:users" (99:100), never as root
RUN mkdir -p /data && chown 99:100 /data
USER 99:100
ENV PYTHONUNBUFFERED=1 DATA_DIR=/data HOME=/tmp
VOLUME /data
EXPOSE 8094
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8094/healthz', timeout=4)"

CMD ["python", "-m", "gamenight"]
