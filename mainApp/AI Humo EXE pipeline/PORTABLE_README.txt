AIHuMo Data Studio — Portable Windows Preview
=============================================

BUILD-INFO.txt lists the package version and the source commit when available.

SYSTEM
  Windows 10 or Windows 11, 64-bit.

STARTING THE APP
  1. Extract the entire ZIP to a normal writable folder.
  2. Keep every bundled file and folder together.
  3. Double-click "AIHuMo Data Studio.exe".
  4. Windows SmartScreen may show an unrecognized-publisher warning because
     this preview is not code-signed. Choose More info, then Run anyway only
     if you received the ZIP from the project owner.

DATA AND PRIVACY
  This preview contains no participant recordings or annotations.
  New processed data is stored under data\processed inside the extracted app
  folder. The .aihumo folder stores local settings and recent-work history.
  Videos and pose data are processed locally; the app does not upload them.

RECORDING REQUIREMENTS
  The MediaPipe full pose model and the default processing configuration are
  included. Use Mode 0 to process a new recording before annotation or graph
  review.

PORTABLE PREVIEW LIMITATIONS
  - The app is not yet code-signed or installed through a Windows installer.
  - Moving or deleting the extracted folder also moves or deletes data stored
    inside it. Back up data\processed before replacing the preview.
  - GPU acceleration and automatic updates are not included in this version.

TROUBLESHOOTING
  If the app does not open, copy the complete extracted folder to a short path
  such as C:\AIHuMo and try again. Do not run it directly from inside the ZIP.
