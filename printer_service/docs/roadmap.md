# Roadmap

Where LabelJetty is heading. The core (library, REST API, job queue + worker, web UI, Homebox
integration, and multi-token / multi-user auth) is functional today; see [Design](design.md) for
how it all fits together. This page tracks what's planned next.

> This is an early project, still tested as a beta by the developer - priorities may shift.
> Feedback and pull requests are very welcome: open an [issue](../../issues).

## Recently shipped

- **Config via the web UI** - set `SETTINGS_UI_ENABLED=true` for a `/ui/settings` page that
  edits the operational settings (label defaults/profiles, printer selector, Homebox, job
  retention, log level) at runtime. Edits are stored in the database and **override env vars**
  (UI > env > default); secrets and infrastructure stay env-only, and `SETTINGS_LOCKED_KEYS`
  pins chosen fields read-only. The form is generated from the settings model, so new editable
  settings are one metadata flag. See [Settings via the web UI](configuration.md#settings-via-the-web-ui).

- **Printer auto-discovery** - leave `PRINTER_USB` unset and LabelJetty auto-detects a
  connected TSPL printer (matching known vendor ids and USB printer-class devices). It uses
  the printer when exactly one is found, and lists candidates as copy-paste selectors when
  several are. Run `labeljetty-testbench list-printers` to see what it finds. See
  [Find your printer](advanced-usage.md#find-your-printer).

## Planned

### OIDC / SSO authentication

The auth layer is already built around a pluggable provider model and a `Principal` identity
(see [Design → Authentication](design.md#authentication)), specifically so that **OIDC slots in
as a third provider** alongside API tokens and local users - reusing the same session, with no
route changes. The plan is to add `AUTH_OIDC_*` settings and an OIDC callback so the service can
sit behind an identity provider for single sign-on.

### Config via UI — follow-ups

The operational settings page shipped (see [Recently shipped](#recently-shipped)). Still open:

- **Secrets in the UI** (masked, write-only): `HOMEBOX_API_KEY` and friends, so a Pi image can
  be fully provisioned from the browser. The field metadata already carries a `secret` flag.
- **A role model** (`admin` users) so the page can be exposed safely in `open` mode and offer
  true per-admin vs per-user hierarchy — today it's gated only by `SETTINGS_UI_ENABLED` + auth.
- **API tokens in the UI** (`AUTH_TOKENS`) — login users and `AUTH_MODE` are now editable from
  the settings page (passwords hashed server-side, anti-lockout guard enforced); machine tokens
  and `SESSION_SECRET` stay env-only for now.

### Increase gama for images

On my printer any images are very dark. Lets have a gamme slider for image printing to make images brighter


## Possible / under consideration

These are ideas, not commitments (carried over from [Design → Non-goals](design.md#non-goals)):

- **Raw port-9100 (JetDirect) socket** so power users can add LabelJetty as a network printer
  manually. (Full IPP Everywhere / driverless discovery is project-sized and fights the "minimal
  dependency" principle - better as its own repo.)
- **Label template library** - named, reusable layouts beyond the Homebox one.
- **Multi-printer support** - the architecture currently assumes a single printer.
- **Broader hardware coverage** - verified support for printers other than the reference Vretti
  420B. This grows from user reports; see [Hardware](hardware.md) and please share your results.
- **Batch printing**: Print a label multiple times
- **Batch template printing**: some kind of simple template designer to print batches of labels given sequential numbers or a csv list to fill out the template.
- **Image image manipulation** Let the user crop and/or rotate an uploaded image to better fit a label

## Explicit non-goals

See [Design → Non-goals](design.md#non-goals): replacing CUPS / being a full spooler, supporting
non-TSPL languages (ZPL/EPL), and cloud / multi-tenant hosting.
