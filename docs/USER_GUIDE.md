# CAMS user guide

This guide takes you from a fresh install to finding people on your campus.
The same guide is inside CAMS under **How to use CAMS**, with a **Show me around** tour.

## 1. First start

Open **CAMS** from the desktop. The setup wizard asks for:

1. The name of your school or company.
2. An **admin** account (username and password of at least 8 characters with letters and numbers).
3. Your agreement to the privacy rules (consent, signs, limited access).

After this, CAMS shows a short tour of the screen.

## 2. Add cameras

Open **Cameras** and press **Add camera**.

- Use **Help me build the address**: choose the brand, type the camera's IP address, username,
  password and (for NVR/DVR recorders) the channel number. CAMS writes the address for you.
- Press **Test connection**. You should see a picture.
- **USB webcam:** type `0` as the address (`1`, `2` for more webcams).
- **Phone as a camera:** install an "IP Webcam" app and use `http://PHONE-IP:8080/video`.
- Don't know the IP? Press **Find on network**. CAMS lists devices with a camera port open.
- Tick **Restricted area** for places where strangers should not be (staff room, server room,
  stores). CAMS will alert you when someone who is not enrolled appears there.

Common addresses (replace USER, PASSWORD, IP):

| Brand | Address |
| --- | --- |
| Hikvision / HiLook | `rtsp://USER:PASSWORD@IP:554/Streaming/Channels/101` |
| Dahua / Imou | `rtsp://USER:PASSWORD@IP:554/cam/realmonitor?channel=1&subtype=0` |
| Uniview | `rtsp://USER:PASSWORD@IP:554/unicast/c1/s0/live` |
| TP-Link Tapo / VIGI | `rtsp://USER:PASSWORD@IP:554/stream1` |
| Reolink | `rtsp://USER:PASSWORD@IP:554/h264Preview_01_main` |

Tip: cameras for recognition work best at head height (2-3 m), pointing at doorways and gates where
people walk *towards* the camera.

## 3. Build your campus map

Open **Campus builder**.

1. Under **Site**, press **Add map picture** if you have a plan or a satellite screenshot of the
   compound. Then type its real **width** and **depth** in metres so distances are correct.
2. Choose **Draw a rectangle** and drag over each building, or **Draw any shape** and click each
   corner (click the first corner again or press Enter to finish).
3. Name each shape and choose its type: building, zone, gate, field or parking. Buildings get a
   height and number of floors for the 3D view.
4. Under **Cameras**, choose a camera that is not on the map yet, then click where it is mounted.
5. Drag the **amber handle** so the cone points the way the camera looks. You can also set the
   building and floor it is on.
6. Press **3D** (top right of the map) to see the campus in 3D.

## 4. Add people and capture their faces

Open **People**.

- **Add person:** name, ID number, type (student, staff, visitor, contractor), class or department.
- **Import list:** a CSV file (from Excel: *Save as CSV*) with the columns
  `full_name, person_code, category, group_name`.
- **Consent:** tick that written consent was given, by whom and when. For students under 18 the
  parent or guardian gives consent.
- **Watch list:** CAMS alerts you every time this person is seen.

Then press **Capture face**:

- **This PC's webcam:** the person sits in front of the webcam. CAMS asks them to look straight,
  left, right, up and down, and takes each picture by itself when the pose is right.
- **A CAMS camera:** choose a camera, ask the person to stand close and follow the instruction,
  then press **Take picture now** for each angle.
- **Upload photos instead:** clear photos with only this person's face.

More angles give better recognition on cameras mounted high or to the side. The squares in the
People list show which angles each person has.

## 5. Find a person

Open **Find a person** and type a name or ID number.

- CAMS shows **when and where the person was last seen**, the last face picture, their path on the
  map (amber dashed line, pulsing pin at the last place) and a timeline.
- Change the period: last 24 hours, today, last 7 or 30 days.
- **Search by photo:** choose a photo (for example of a visitor); CAMS shows the most similar
  enrolled people. Always check with your own eyes before acting on a result.

## 6. Live cameras and alerts

- **Live cameras** shows all cameras. Green box = recognised, red = not enrolled (face blurred),
  orange = on the watch list. Double-click a camera for full screen.
- **Alerts** lists watch-list sightings, strangers on restricted cameras and offline cameras.
  New alerts also pop up in the corner. Press **Seen** when handled.

## 7. Settings (admin)

- **Match strictness:** if CAMS confuses two people, move it right; if it misses people, move it left.
- **Pictures checked per second:** lower it if the PC is slow.
- **Privacy:** blur strangers, keep face pictures with sightings, delete sightings after N days.
- **Users:** add an account for each staff member. *Viewer* can watch and search, *Operator* can
  also enrol people and set up cameras, *Admin* can do everything.
- **Backup:** download a backup zip and keep it locked away; it contains personal data.
- **Activity log:** who searched for whom, who enrolled or deleted whom.

## 8. Use CAMS from another PC

Run the installer with **Let other computers on this network open CAMS** ticked (or start
`CAMS.exe --lan`). Other PCs on the same network then open `http://CAMS-PC-IP:8765` in a browser
and sign in with their own account.

## Problems

| Problem | What to do |
| --- | --- |
| Camera says "Cannot connect" | Check the IP (ping it), username, password and the address pattern for the brand. Make sure RTSP is enabled in the camera's settings. |
| Picture is grey or smeared | Use the camera's main stream; check the network cable. |
| A person is not recognised | Capture more angles, in light like the camera's; check the camera sees faces from the front and not too far away (face at least about 40 pixels tall). |
| Two people are confused | Raise match strictness; delete wrong face pictures; capture fresh pictures. |
| The PC is slow | Lower pictures per second in Settings; use fewer cameras per PC. |
| 3D view is empty | The PC's graphics driver does not support WebGL. Use the plan view or update the driver. |
| Forgot the admin password | Another admin can set a new one in Settings, Users. |

Your data is stored in `%APPDATA%\CAMS`. Uninstalling CAMS does not delete it.
