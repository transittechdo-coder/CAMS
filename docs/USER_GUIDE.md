# CAMS user guide

This guide takes you from a fresh install to finding people on your campus.
The same guide is inside CAMS under **How to use CAMS**, with a **Show me around** tour.

## 1. First start

The installer puts a **CAMS** icon on the desktop and in the Start menu, and opens CAMS when it
finishes. Later, double-click the **CAMS** icon on the desktop (or press the Windows key and type
*CAMS*). The first time, the setup wizard asks for:

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

### Activity rules (suspicious activity)

Press **Activity rules** on a camera. CAMS runs a person-detection AI on this PC and can alert you when:

- someone **stays** in view longer than the minutes you set (loitering);
- **N or more people gather** for at least 10 seconds (crowd);
- someone is **running** (much faster than walking);
- **anyone** is seen during the hours you set (closed hours);
- the camera is **covered, blurred or turned away** (tampering).

Each alert comes with a picture of the scene. These rules point out situations for a guard to
look at. They cannot tell what a person intends, so always check before acting.

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
6. **Arrange** a selected building with **Turn left**, **Turn right**, **90°** and **Duplicate**,
   or drag it. Under **Floors**, press **Add floor** and give each floor a name (Ground floor,
   Reading room, ...). Cameras can then be placed on a named floor.
7. Press **3D** (top right of the map) to see the campus in 3D, with floor lines on each building.

### 3D Map Studio (draw the campus in 3D)

In **Campus builder**, press **Open 3D Map Studio**. It works like a game level editor.

**Moving the view**

| To | Do this |
| --- | --- |
| Look around | Hold the right mouse button and move the mouse |
| Fly | W A S D or the arrow keys; Q / E to go down / up; hold Shift to go faster |
| Zoom | Mouse wheel (it zooms towards where you point) |
| Slide the view | Hold the middle button (the wheel) and move |
| Turn around a point | Drag empty space with the left button |
| Walk inside | Press **Walk inside**: move the mouse to look, W A S D to walk, Space to jump, walk into a ladder to climb. Esc stops |
| Quick views | **Top**, **Front**, **Side**, **3D**, and **Focus** (F) to fly to the chosen shape |

**Drawing**

1. Pick a tab on the left (**Shapes**, **Building**, **Roofs**, **Outdoor**, **Objects**) and choose a shape.
2. Click in the view to put it there, or drag to draw its size. Point at the **top** of another shape
   and the new one sits on it, so you can stack blocks, floors and rooms.
3. **Walls, fences, railings, hedges, roads and paths**: click each corner. Esc, a double-click or a
   right-click finishes. Hold Shift for straight lines.
4. **Roofs** and **floor slabs**: point at the top of a building, block or room and click; the roof
   fits itself, with a small overhang. Or choose a building and use **Add roof on top**.
5. **Doors, windows, signs and ladders**: point at a wall and they fix themselves onto it.
6. **Upper floors**: choose a building and press **Add a floor** (anything on its roof moves up too),
   **Add stairs**, or **Stack copy on top**. Use ▲ / ▼ to work on Floor 1, 2 ... and tick
   **Cut above** to hide everything higher so you can see inside.

**Changing shapes**

- Click a shape to choose it (Shift-click for more). Drag it to slide it along the ground.
- **Move** (G), **Turn** (R) and **Size** (T) show coloured handles to drag. **Snap** keeps things on
  the grid; pick the grid size next to it.
- The **Properties** panel sets exact size, position, turn, floors, doors, windows, handrails and more,
  plus colour, material (brick, blocks, tiles, iron sheet, glass, grass, tarmac...) and see-through.
- Ctrl+Z / Ctrl+Y undo and redo, Ctrl+C / Ctrl+V copy and paste, Ctrl+D duplicates, Delete removes,
  Page Up / Page Down raise and lower, H hides. **Objects** lists every shape, with Hide and Lock.
- **Make this an access area** turns a shape into an area here in the Campus builder, so you can
  choose who may enter it.

**Brushes** (the **Tools** tab): **Paint ground**, **Rub out paint**, **Plant trees**, **Draw path**
(footpath, road, hedge, fence or wall by hand), **Delete brush**, **Measure** and **Copy colour**.
[ and ] change the brush size.

**Map** tab: show or hide the site picture and the access areas, time of day, shadows (turn them off
if the view is slow on an older PC), export and import the map as a file, and a sample school block.

Press **Save** (Ctrl+S). The 3D view on **Overview** and **Find a person** then shows your drawn campus,
and you can fly around it there too: right-drag to look and W A S D while the mouse is over the map.

### Restricted areas (who may enter)

Select a building or zone and use **Who may enter**:

- **Everyone may enter** (no rule), **Only the people chosen below**, or
  **Everyone except the people chosen below**.
- Choose people by **type** (students, staff, visitors...), by **class or department**, or by **name**.
- Tick **Closed hours** to be alerted about anyone seen there between two times (for example
  18:00 to 06:00). With *Only the people chosen*, those people may still be there after hours.

Areas with rules have a red dashed outline. When a camera in that area sees someone who is not
allowed, an alert appears with their name and picture. Unknown faces in a restricted area always
cause an alert.

## 4. Add people and capture their faces

Open **People**.

- **Add person:** name, ID number, type (student, staff, visitor, contractor), class or department.
- **Import list:** a CSV file (from Excel: *Save as CSV*) with the columns
  `full_name, person_code, category, group_name`.
- **Consent:** tick that written consent was given, by whom and when. For students under 18 the
  parent or guardian gives consent.
- **Watch list:** CAMS alerts you every time this person is seen.

Then press **Capture face** for a **360° set** of nine views: front, half left, left side,
half right, right side, up, down, back and top.

- **This PC's webcam:** CAMS tells the person which way to turn and takes each face picture by
  itself when the pose is right. Back and top are taken with the button.
- **A CAMS camera:** choose a camera, ask the person to stand close and follow the instruction,
  then press **Take picture now** for each view.
- **Upload photos:** choose which side the photos show (or let CAMS detect it), then pick the files.
- **Upload turn-around video:** film the person slowly turning all the way around for 10-20
  seconds. CAMS picks the best picture for each angle, including the back.

The seven face views are used for recognition; more of them means better results on cameras
mounted high or to the side. The **back and top cannot identify anyone** (no face is visible), so
CAMS keeps them as reference pictures for guards to compare by eye. The squares in the People
list show which of the nine views each person has.

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

## 8. Use CAMS from another PC (optional, for IT staff)

CAMS normally works only on the PC where it is installed. To let other PCs on the same network
sign in, an IT person can start `CAMS.exe --lan` and allow port 8765 in Windows Firewall (this
step needs administrator rights). Other PCs then open `http://CAMS-PC-IP:8765` in a browser.

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
