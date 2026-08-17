# OK-141 Platform authorization cause diagnostic v1

After the registration audience remediation, all three bound Applications
observe the expected Git revision but remain `Sync=Unknown` with authorization
conditions. This diagnostic performs one exact read of each Application and
extracts only normalized RBAC facts from its condition messages.

Raw messages, subjects, API endpoints and namespace names outside the two bound
target namespaces are not retained. The output is suitable for designing a
minimal RBAC amendment; it does not grant or apply that amendment.
