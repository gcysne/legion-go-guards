# Security

Report security problems privately through GitHub's
[security advisories](https://github.com/gcysne/legion-go-guards/security/advisories/new), not in a public issue.

What the project does with privileges: the services run as your user and only read sensors, the journal and crash
folders. The only root step is the installer copying the Decky plugin into `~/homebrew/plugins` (owned by root),
with your password, after saying why. The plugin checks GitHub's public releases API for updates; nothing else is
sent anywhere.
