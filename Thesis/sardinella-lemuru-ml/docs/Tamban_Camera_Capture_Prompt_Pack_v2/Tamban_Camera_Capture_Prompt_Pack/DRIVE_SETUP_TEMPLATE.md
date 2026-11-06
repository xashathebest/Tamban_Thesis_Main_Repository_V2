# Google Drive destination details — user fills in later

**Important:** Share folder URLs/IDs only. Do NOT paste passwords, OAuth refresh tokens, client secrets, or a service-account private key into a prompt, issue, or repository. Configure secrets using a secure local runtime procedure after authorization.

1. **Google Drive destination folder URL**: `[TO BE PROVIDED]`
2. **Optional second destination / backup folder URL**: `[TO BE PROVIDED OR NONE]`
3. **Drive type**: `[Personal My Drive / Shared Drive / Unknown]`
4. **Account that should own the uploaded files**: `[OWNER TO CONFIRM]`
5. **Authorization method**: `[OAuth 2.0 consent / Service account with explicit folder permission / Discuss before choosing]`
6. **Auto-sync on saving a frame?** `[Yes (opt-in) / Manual sync]`
7. **Suggested subfolders**: `YYYY-MM-DD/<session-id>/raw` + manifest files
8. **Allow offline local-first backup?** `Yes — mandatory to prevent data loss`
9. **Accepted file format**: `[JPEG Q95 / PNG if supported; keep native frame dimensions]`
10. **Privacy/consent policy for vendor/source metadata**: `[TO BE CONFIRMED]`

Folder URL alone provides a destination, **not Drive API authorization**. Before accepting sync as working, verify read/write permission with owner-approved test media and surface real Drive file IDs in the UI.
