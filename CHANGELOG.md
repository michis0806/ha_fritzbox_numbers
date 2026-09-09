# Changelog

All notable changes to this integration are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-09-09

Initial release.

### Added

- One device per phone number below the FRITZ!Box hub device, linked via
  `via_device_id`.
- A **connectivity** binary sensor per number, on while the number is registered.
- A **registration status** diagnostic sensor per number with the raw status text
  from the box.
- A **registered numbers** sensor on the box, counting registered numbers and
  listing the unregistered ones in an attribute.
- Config flow with host, username and password, using the box serial number as the
  unique ID, plus re-authentication when the credentials stop working.
- Values are polled every 5 minutes; on failures the last known values are kept for
  up to 30 minutes. Numbers seen once are remembered so their entities survive an
  outage as `unavailable`.

[1.0.0]: https://github.com/michis0806/ha_fritzbox_numbers/releases/tag/v1.0.0
