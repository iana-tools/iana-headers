# IANA source snapshots

`make sync` saves the source files used by each IANA sync under `snapshots/YYYY-MM-DD/`, alongside the processed records in `../db/`. Each dated directory has a manifest listing the captured source paths and original IANA URLs.

These snapshots are immutable, reviewable source inputs. Commit them with the corresponding `../db/` and generated-header changes when appropriate. The workflow does not stage or commit automatically. The mutable runtime cache remains in `../c/cache/` and is ignored by Git. Dated snapshots can also be used directly as offline parser regression fixtures.
