# EDTools default catalogue

`default.json` is a validated, bundled baseline of the public resources:

- https://edtools.cc/pve.json — mission source/target pairs and source coordinates.
- https://edtools.cc/res.json — recorded RES/CNB sites.

Source: EDTools, CMDR VicTic and contributors. Retrieval times, original resource
URLs, HTTP Last-Modified values and normalized content SHA256 values are embedded
in the file. Retrieval time is not the upstream data's own update time.

This is recorded candidate data, not a live mission board, guaranteed RES
availability, current BGS state or independently verified gameplay evidence.
The application's source-code license must not be construed as relicensing
third-party data. Retain source attribution when distributing the baseline.

The application reads this file as an immutable default. User-confirmed updates
are saved separately in the application data directory and take precedence.
Normal searches do not expire or refresh this catalogue; dynamic Spansh data uses
its existing separate caching policy.

Maintainers can deliberately regenerate the baseline before a future build:

```text
python scripts/update_bundled_edtools.py
```

Both downloaded resources must pass the application's schema checks before the
script atomically replaces the bundled baseline. Builds themselves never fetch
data. PyInstaller includes `default.json` via `EliteDangerousFilter.spec`.
