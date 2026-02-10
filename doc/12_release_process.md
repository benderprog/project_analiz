# Release process

## Tagging conventions

* Git tags cannot contain spaces. Use tags like `ver-1.1` (or `ver.1.1`).
* GitHub Release titles can include spaces, for example **"ver. 1.1"**.
* Release bundle version arguments use the dotted version (for example, `1.1`), and the bundle folder is named `release_ver_1_1`.

## Offline / closed-contour release docs

* Dump-first workflow (pg15-in-docker): [`doc/16_offline_dump_first_bundle.md`](./16_offline_dump_first_bundle.md).
* Bundle runbook entrypoint: [`doc/offline/README.md`](./offline/README.md).
