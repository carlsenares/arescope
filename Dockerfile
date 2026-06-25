FROM python:3.12-slim

WORKDIR /app

# Build deps for psycopg / cryptography wheels are usually prebuilt; keep slim.
COPY pyproject.toml ./
COPY arescope ./arescope
# Include the [connectors] extra so Holehe + Maigret (and their dep trees, incl.
# trio) ship in the deployed worker — without it they degrade to coverage gaps
# and those tools never actually run.
RUN pip install --no-cache-dir ".[connectors]"

# GHunt (email -> Google photo / Maps locations, #5) in its OWN venv: it pins
# httpx==0.27.2, which conflicts with arescope's httpx>=0.28. The connector only shells
# out to the `ghunt` binary, so an isolated env + a PATH symlink is all it needs — no
# shared-dependency fight. Absent/expired Google cookie still degrades to a coverage gap.
COPY scripts/patch_ghunt_people.py /tmp/patch_ghunt_people.py
RUN python -m venv /opt/ghunt-venv \
    && /opt/ghunt-venv/bin/pip install --no-cache-dir "ghunt==2.3.4" \
    && ln -s /opt/ghunt-venv/bin/ghunt /usr/local/bin/ghunt \
    # ghunt 2.3.4 (last release, unmaintained) crashes on Google's current people API
    # (KeyError: 'container') before returning anything. Guard the photo lookups so the
    # email lookup completes and the profile photo / Maps data land. Fail-soft.
    && /opt/ghunt-venv/bin/python /tmp/patch_ghunt_people.py \
        /opt/ghunt-venv/lib/python3.12/site-packages/ghunt

# Camoufox stealth browser (admin/demo public-content connectors: Instagram, …).
# OPTIONAL + heavy: pulls Playwright + downloads a patched Firefox (~100MB) and its
# system libs. The connectors degrade to a coverage gap when it's absent, so the image
# builds fine without it. Uncomment to enable, then rebuild the api+worker images.
# (Left commented because it's unvalidated end-to-end and the exact apt set may need a
#  tweak per base image — enable deliberately, don't let it silently bloat the build.)
# RUN apt-get update && apt-get install -y --no-install-recommends \
#         libgtk-3-0 libx11-xcb1 libasound2 libdbus-glib-1-2 libxtst6 libxrandr2 \
#     && rm -rf /var/lib/apt/lists/* \
#     && pip install --no-cache-dir ".[browser]" \
#     && python -m camoufox fetch

ENV PYTHONUNBUFFERED=1
