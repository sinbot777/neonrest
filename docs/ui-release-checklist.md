# UI styling review before release acceptance

Apply this review to every interface change, including small fixes and shared
templates. The Service profile fix did not cover its separate workspace template;
review related views explicitly rather than assuming shared branding means shared
styling.

- Inspect the actual rendered page on desktop and at 390px. Check horizontal
  overflow, wrapping, spacing, headings and readable field/control sizes.
- Inspect every affected view of a shared template: list/workspace, management,
  composer, empty and error states where applicable. Do not change real account
  settings or publish content just to inspect a view.
- Check links against the actual page background, including visited, hover and
  keyboard focus states. Plain links must be identifiable; action links should
  use consistent controls with at least 44px touch targets.
- Check text/link contrast (4.5:1 for normal text, 3:1 for large text), form labels,
  visible keyboard focus and usable navigation order. Review forced-colors rules
  and both supported Day/Night themes when the surface follows those themes.
- Inspect final computed styles with the real shared stylesheets loaded, including
  button colors, background, height and focus outline. A component selector can
  lose to a broader shared rule even when its own declarations look correct.
- Check the live deployed page after reload; template compilation and HTTP 200
  alone do not prove correct styling. Save a screenshot without private content
  and record the views/sizes actually reviewed in the release or PR evidence.
- Keep actual-device and assistive-technology checks distinct from viewport and
  DOM checks. Document any acceptance still pending instead of marking it done.
