8 ref_sdfconfig
###############

API Breaks
----------
- Users without sdfconfig access will no longer be able
  to use switchtool effectively.
- Non-GUI code branches that use netconfig are disabled.
- Subnet names were changed to match sdfconfig

Features
--------
- N/A

Bugfixes
--------
- Various functions that were trivially broken with
  e.g. NameError, AttributeError have been fixed.

Maintenance
-----------
- Use sdfconfig instead of netconfig, which has been
  deprecated and scheduled for removal.

Contributors
------------
- zllentz
