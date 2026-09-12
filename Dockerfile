# The narrate-service container. The service only -- never the engine, which
# is its own image and its own container (see compose.yaml).
#
# Pinned by tag AND digest. The tag says what it is for a reader; the digest is
# what actually makes the build reproducible, because a tag is a moving pointer
# and `python:3.14-slim` will mean something different next month.
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6

# ⛔ No `pip install` of anything. The service is standard library only, which
# is what makes this image a copy of the source onto a base image and nothing
# else: no build-time network access, no resolver, no lockfile to go stale.

# A non-root user, and the artifact directory is created owned by it BEFORE the
# volume is mounted. A bind or named volume whose mount point is absent from
# the image is created root-owned by docker, and the service could then never
# write into it.
RUN useradd --create-home --uid 10001 narrate \
 && mkdir -p /var/lib/narrate/artifacts \
 && chown -R narrate:narrate /var/lib/narrate

WORKDIR /srv/narrate
COPY narrate/ /srv/narrate/narrate/

USER narrate

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NARRATE_ARTIFACT_DIR=/var/lib/narrate/artifacts \
    NARRATE_PORT=8870

# ⛔ 0.0.0.0 INSIDE THE CONTAINER ONLY, and the distinction is the whole point.
# A container's own interfaces are not the host's; what decides who can reach
# this service is the `ports:` line in compose.yaml, which binds 127.0.0.1 on
# the host. Binding loopback in here would make the service unreachable from
# the published port and tempt somebody to publish it with host networking
# instead -- which is the outcome the loopback rule exists to prevent.
ENV NARRATE_BIND=0.0.0.0

EXPOSE 8870

# No shell form, so the service is PID 1 and receives the stop signal directly
# rather than through a shell that ignores it.
CMD ["python3", "-m", "narrate", "serve"]
