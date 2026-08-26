---
module: dental_3d
last_verified_commit: ec741ed
---

# dental_3d — events

Per-module slice of [`docs/events-catalog.md`](../../events-catalog.md)
(auto-generated). Update both files when adding or removing events.

## Published

None. The dental 3D scene is fetched on demand; mutating it only
changes presentation state (visibility / colour override), which no
other module reacts to today. Phase 2 mesh ingestion publishes no
dental_3d event of its own — the media module's `DOCUMENT_UPLOADED`
fires from `DocumentService.create_document` for every ingested scan
(publisher: media). If a future phase needs to announce scene changes
(e.g. a segmentation job finishing), publish through `event_bus` and
add the `EventType` constant first — see the root `CLAUDE.md` "When
adding X" checklist.

## Subscribed

None. Presence and conditions are read from the odontogram at request
time (pull, not push), and real meshes are discovered by querying the
patient's media documents on each scene read — archival and ownership
changes are therefore reflected immediately without an event handler.
An event-driven cache refresh is a possible future optimization, not a
correctness need.
