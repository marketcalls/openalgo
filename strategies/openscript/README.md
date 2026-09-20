# OpenScript studies

Your OpenScript studies live here, one `.oscript` file each.

Nothing in this folder is committed, and `git pull` never touches it. On Docker
the folder is a named volume, so a container rebuild leaves your scripts where
they were.

A name may hold letters, digits, dots, dashes and underscores, must start with a
letter or a digit, and ends in `.oscript`. A file may be up to 256 kB.

A `.bak` beside a script is the previous version, kept automatically whenever a
save replaces one.

See [docs/openscript.md](../../docs/openscript.md) for what the language is,
how it differs from the custom indicators in `../indicators/`, and why a study
from a stranger is a smaller decision here than it is there.
