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

1. Under **Site**, press **Use a real satellite map** (see below), or press **Add map picture** if
   you have your own plan of the compound and type its real **width** and **depth** in metres.
2. Choose **Draw a rectangle** and drag over each building, or **Draw any shape** and click each
   corner (click the first corner again or press Enter to finish).
3. Name each shape and choose its type: building, zone, gate, field or parking. Buildings get a
   height and number of floors for the 3D view.
4. Under **Cameras**, choose a camera that is not on the map yet, then click where it is mounted.
   Press **New camera** to add another camera at any time (even when all cameras are already on
   the map), then click where it hangs. Open **On the map** and press **Move** to give a placed
   camera a new spot.
5. Drag the **amber handle** so the cone points the way the camera looks. You can also set the
   building and floor it is on.
6. **Arrange** a selected building with **Turn left**, **Turn right**, **90°** and **Duplicate**,
   or drag it. Under **Floors**, press **Add floor** and give each floor a name (Ground floor,
   Reading room, ...). Cameras can then be placed on a named floor.
7. Press **3D** (top right of the map) to see the campus in 3D, with floor lines on each building.

### Hologram view (see-through 3D)

In any 3D view (the **3D** button on a map, or the 3D Map Studio) press **Hologram**. The campus
becomes a digital blueprint: see-through teal walls with bright edges, darker floors and
structure, cameras as small glowing shapes, on a dark background with a faint grid and range
circle, so you can see rooms, stairs and cameras inside every building at once. On the maps the
model turns slowly by itself; press the round pause button (top right) to stop it, or just drag to
turn it yourself. A legend runs along the top and the site's GPS position is shown at the bottom.
Press **Hologram** again for the normal look. CAMS remembers your choice.

In the 3D Map Studio, the **CCTV camera** tool (Tools tab) lists your cameras: **Place** puts a
camera that is not on the map yet (click on the ground, a floor or a wall), **Move** gives a camera
a new place, and **+ Add a new camera** adds another camera to CAMS and lets you place it.

### Real satellite map and exact GPS positions

1. In **Campus builder > Site**, press **Use a real satellite map**.
2. Type the place name (for example *Mikocheni, Dar es Salaam*), paste a Google Maps link, or type
   the coordinates (`-6.7627, 39.2443`), and press **Find**. You can also just drag and zoom.
3. Move and zoom until the whole compound sits inside the amber box. The box shows its size in metres.
4. Press **Use this area**. CAMS downloads the satellite picture (the internet is needed only for
   this step), saves it, and sets the map size for you. After that it works fully offline.

Buildings and cameras you drew before stay in the same place on the ground. Once the map is on a
satellite picture, CAMS knows the **exact GPS position** of every camera and sighting: it shows it
under the mouse on the map, on **Find a person** (*Exact place*) and on each stop of a route. Press
the copy button next to a position and paste it into Google Maps or a phone to go there.
**Only save the position** keeps your own plan picture and just tells CAMS where it is on Earth.

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

### What each part of the map is used for

Select an area in the Campus builder and choose **Used for** (Dining hall, Classroom, Library,
Dormitory, Sports ground, Chapel / mosque, Assembly, Office, Gate...). The activity AI and the
routines use this. If you leave it empty, CAMS guesses from the name ("Dining Hall", "DH",
"Form 5 class", "Library", "Dorm"...).

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

- CAMS shows **when and where the person was last seen**, the exact GPS position of that place and
  the last face picture.
- **Route:** the map draws a line from building to building in the order the person went, with
  arrows showing the direction and a numbered stop for each place (1 = first place in the period,
  the amber stop = now). Each stop has a small picture of the person; press it to **watch the
  clip** of the moment they were seen there. The list beside the map shows the same stops with
  times, how long they stayed and a **Watch** button; the line above reads like
  *Asha went from Main gate → Block A → Library*.
- Change the period: the last hour, 3, 6 or 12 hours. The list is split into hours (*08:00 – 09:00, this
  hour*), and on the map older parts of the route are fainter, so you can see the order at a glance.
- Routes are kept for **12 hours** and then deleted by themselves, so CAMS stays small and fast.
  Change this in **Settings → Data and storage**.
- **Search by photo:** choose a photo (for example of a visitor); CAMS shows the most similar
  enrolled people. Always check with your own eyes before acting on a result.

## 6. Live cameras, recordings and alerts

- **Live cameras** shows all cameras. Green box = recognised, red = not enrolled (face blurred),
  orange = on the watch list. Double-click a camera for full screen.
- **Record:** press **Record** on a camera to save its video; press **Stop** to finish. A red
  **REC** badge shows while it records. To record a camera all the time, tick **Record this camera
  all the time** in its settings on the **Cameras** page.
- **Recordings** lists the saved videos by day. **Play** watches a video inside CAMS (pause, jump,
  2x-8x speed); **Download** saves the .mp4 file to the Downloads folder; **Keep** protects it
  from automatic deletion.
- **Download a part:** on **Recordings**, choose the camera, the day and the time from / to, then
  press **Download this part**. The bar shows which times were recorded (click it to pick a time).
- **Colour at night:** most CCTV cameras turn black and white at night (infrared). CAMS can colour
  that video live with an AI:
  1. In **Settings > Colour for black-and-white (night) video**, press **Download the colour AI**
     (about 130 MB, internet needed once). With no internet, copy the file `colorizer.onnx` onto a
     USB stick on another PC and press **Load colorizer.onnx from this PC**.
  2. On **Cameras**, press **Edit** on a camera and choose **Colour for black-and-white video**:
     *Automatic* (only when the camera shows black and white) or *Always* (an old black-and-white
     camera).
  Coloured pictures are marked **AI colour**. The colours are the AI's guess: **never trust the
  colour of clothes or a car in AI-coloured video.** CAMS also makes dark night pictures clearer;
  you can switch this off. On a slow PC choose **Colour AI speed: Light**. Face recognition always
  uses the camera's real picture.
- **Alerts** lists watch-list sightings, strangers on restricted cameras and offline cameras.
  New alerts also pop up in the corner. Press **Seen** when handled.

### Emergencies: fire, smoke, person down

Every camera watches for three emergencies, so help can come before it is too late:

- **Fire:** flame-coloured areas (or glowing white ones on black-and-white night cameras) that
  appear, flicker and stay in one place for a few seconds. An orange wall, a lamp or a red car does
  not count.
- **Heavy smoke:** a grey haze that hides part of what the camera normally sees, for several
  seconds. Lights going off or the camera switching to night mode do not count.
- **Person down:** someone lying on the ground for 20 seconds (choose the time per camera), or
  8 seconds after a fall (standing, then suddenly on the ground). Uses the person-detection AI and,
  when installed, the body-pose AI, so it works even when the face cannot be seen. Beds, sofas and
  dormitories do not count.

When one is seen, **every CAMS window turns red with a siren**, showing the camera's picture with the
place marked, the camera and building, and the time. The computer running CAMS also beeps through its
speakers, even if the window is closed. Press **Watch the camera** to look, then **I'm handling it**
once someone is on the way. **Mute sound** stops the siren but keeps the red screen; a new emergency
sounds again.

- Turn any of the three off per camera in **Cameras → Activity rules** (for example fire for a
  kitchen camera that sees cooking fires).
- **Settings → Emergencies:** how easily they trigger (*Low*, *Normal*, *High*), the beep on this
  computer, and **Test the alarm** to check every window shows it.
- These are early warnings from cameras and can be wrong both ways. Keep smoke detectors, fire
  alarms and a first-aid plan. Tanzania emergency numbers: **114** fire and rescue, **112** general.

## Visitors

Open **Visitors → Check in a visitor**. Type the name, phone, who they are visiting, the reason and
how long they stay (and, if your site asks, an ID or badge number). You can tick the only places they
may go (for example only the Administration block). Then take their face photo with the webcam, a
camera or a photo. Tell the visitor that cameras follow them while they are inside.

- The visitor is recognised on every camera, and **Track** shows their route like anyone else's.
- **Alerts:** a visitor seen outside their places, and a visitor still inside after the time they
  said they would leave (with where they were last seen). **More time** extends the visit.
- **Pass** prints a visitor pass with photo, host and time.
- **Check out** when they leave: CAMS deletes their face print at once and stops recognising them.
  The visit stays in the **Visitor log** for 30 days (Settings → Data and storage), then it is deleted.

## Vehicles (number plates)

For a gate camera, open **Cameras → Activity rules** and tick **Read number plates**. Every vehicle
that comes in or out is listed in **Vehicles** with the time, the camera and a picture of the plate.

- Mark a plate **Known** (staff car, school bus, delivery van, with the owner's name) or **Flag** it to
  get an alert whenever it comes. **Alert for any vehicle that is not on the known list** suits gates
  where only known cars may enter.
- Point the camera at the plates, not from too high; plates should be at least about 20 pixels tall
  in the picture. Night vision (infrared) helps after dark.
- The reader can mistake similar characters (0 and O, 8 and B); CAMS matches those to your list
  anyway. Always check the plate picture before acting.

## Guards' phones: the CAMS Guard app

Guards get CAMS alarms on their phones over the site's Wi-Fi. Nothing goes over the internet.

**Once, on the CAMS computer:** Settings → Phones → tick **Allow phones on this network**, then close
CAMS and open it again. (The first time, Windows may ask to let CAMS through the firewall: choose
*Private networks* and press *Allow*.)

**For each guard's phone (about one minute):**

1. Connect the phone to the site's Wi-Fi.
2. On the CAMS computer: Settings → Phones → **Add a phone**. Choose the guard, or type a new guard's
   name. A big QR code appears.
3. **The phone does not have the app yet:** open the phone's camera, point it at the code and press the
   link. Press **Install the app** (allow installing from the browser if the phone asks). The app comes
   from the CAMS computer: no internet and no Play Store needed.
4. Open **CAMS Guard**, press **Scan the code** and point the phone at the same code.
5. Press **Allow** on the questions the phone asks (notifications, running in the background, alarm on
   the locked screen).

That is all: no address, user name or password to type. The phone stays connected for a year.

**What the guard sees:** a green bar *All is well*. For fire, heavy smoke or a person down, the phone
rings loudly (also on silent and when locked), vibrates and shows a red screen with the camera's picture
and one big button, **I'm handling it**. Other alerts (a visitor who stayed too long, a flagged vehicle,
a bag left behind...) come as normal notifications. Below the bar are the guard screens: alerts,
cameras, visitors inside (with Check out) and find a person.

- **Lost phone or a guard leaves:** Settings → Phones → **Disconnect**. That phone stops at once.
- If the CAMS computer's address changes, the app finds it again by itself.
- If the phone cannot reach CAMS for a minute and a half, it says so, so the guard knows alarms cannot
  arrive (for example when the phone left the Wi-Fi).
- iPhones: point the camera at the same code and press the link to use the guard page in the browser
  (keep it open: an iPhone can only ring while the page is open).

## Power cuts and System health

- **Start CAMS when this computer turns on** (System health page, and ticked in the installer). Also set
  the computer to turn on by itself when power returns: in the BIOS / UEFI this is called *Restore on AC
  power loss* or *AC back: Power on*. A UPS keeps CAMS and the cameras running through short cuts.
- After a power cut, CAMS writes an alert saying how long it was off: there are no recordings for that
  time. All the gaps are listed on the **System health** page.
- On a laptop, or a PC with a UPS that tells Windows its battery level, CAMS alerts when power goes off,
  when the battery is almost empty, and when power is back.
- **System health** shows each camera (working, how many pictures a second, offline for how long), the
  disk, the AI models, the computer's load and when the last backup was made.

## Bag left behind

In **Cameras → Activity rules**, set **Bag left behind** to a number of minutes (try 3 for gates,
halls and corridors). CAMS alerts when a backpack, handbag or suitcase stays that long with nobody near
it, with a picture of the bag marked. Leave it at 0 for classrooms, where bags stay all day.

## 7. Settings (admin)

- **Match strictness:** if CAMS confuses two people, move it right; if it misses people, move it left.
- **Pictures checked per second:** lower it if the PC is slow.
- **Face AI speed:** *Automatic* picks *Fast* on PCs with 4 or fewer processor cores. *Detailed* finds
  faces further from the camera but needs a strong PC. In every mode CAMS does not work out a face
  again while it stays in the same place, and checks cameras where nothing moves less often.
- **Maps and mouse** (every user): **Swapped** makes the **right** mouse button move the map (and
  turn around a point in 3D) and the left button look around in 3D. Clicking to choose and draw
  stays on the left button. The middle button (wheel) always moves the map.
- **Privacy:** blur strangers, keep face pictures with sightings.
- **Data and storage:** choose how long CAMS keeps each kind of data, see how much space each uses,
  and **Delete now** any of them:
  - *Routes* (where people were seen, with face pictures and clips): 12 hours unless you change it.
  - *Alerts*, *Activity timeline and notes*: 30 days. *Camera recordings*: 7 days (videos marked
    Keep stay).
  - *Saved satellite map*: only the parts you look at are downloaded, up to 300 MB.
  - *Always keep free on the disk* (5 GB): if the disk gets that full, the oldest videos go first.
  CAMS cleans up by itself every 10 minutes. People, cameras, maps and settings are never deleted
  automatically. *Never delete* keeps that kind of data for ever.
- **Video recordings and clips:** short clips of each sighting on/off and their length, recording
  speed and size, and the disk space recordings may use (the oldest are deleted first when it is full).
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


## Activity timeline, routines and the daily report

CAMS writes a **timeline** for every person it recognises: what they were doing, where and when,
for example *8:00 AM – 10:00 AM Sitting, Form 5 PCM class*. Open a person (People page) and scroll to
**Day timeline**. Use ‹ › to look at other days.

**How it knows what someone is doing.** When a camera recognises a face, CAMS keeps following that
person's body even when they turn away. About every 2 seconds it looks at:

- the **body** (a pose AI finds 33 body points): sitting or standing, lying down, a hand at the mouth,
  a hand raised, head down over a book;
- **things** near the person or in their hands: plates, cups, spoons, food, books, phones, laptops,
  balls, chairs, beds, tables;
- **movement**: walking or running;
- the **place** and what it is used for.

Built-in activities: eating or drinking, sitting, standing, walking, running, lying down, sleeping
or resting, reading or writing, using a phone, using a computer, playing sport, raising a hand, with
a group. Everything runs on the PC.

### Teach CAMS your own activities

Open **Activity & routines → Teach the AI**.

1. Type a new activity (for example *Sweeping*, *Praying*, *Queueing for food*) and press **Add activity**.
2. Below are the pictures CAMS took. For each one choose what the person is really doing, or press
   **Correct ✓** when the AI was right. **Remove** throws away a picture that is not useful.
3. After **3 examples** of an activity CAMS starts recognising it by itself, and it gets better with
   every example.

You can also press **Correct** on any entry in a person's Day timeline. Your answer fixes the entry and
teaches the AI at the same time.

### Place & time rules

Some activities cannot be seen from the body alone. In **Place & time rules** say, for example, *in
the Chapel from 07:00 to 07:30 on weekdays = Morning prayers*, or *in any Library from 19:30 to
21:00, sitting = Evening prep*. Rules win over the AI.

### Routines (where people should be)

In **Activity & routines → Routines**, press **Add routine** or a **Quick start** button:

- **Name, From, Until, Days**: e.g. *Lunch, 13:00 to 13:45, Monday to Friday*.
- **Place**: any place of a kind (all dining halls) or particular areas.
- **People should be there** (note who missed it or came late), or **NOT be there**
  (e.g. not in the dormitory during lessons).
- **Who**: types of people and classes. Leave empty for everyone.
- **Late after**: minutes before someone counts as late.
- Tick **Also raise an alert** to get an alert as well as a note.

A couple of minutes after a routine ends, CAMS writes a note on each person's timeline, for example:

> *Godwill did not go to the Dining Hall during Lunch (1:00–1:45 PM). Godwill was seen in the Library at 1:05–1:45 PM, reading or writing.*

Only people a camera saw that day are checked, so someone who stayed at home is not marked as
missing lunch. *Not seen in the dining hall* can also mean no camera saw them there: put cameras at
the doors of places you check, and look before acting on a note.

### Habits

Each person's page shows their **usual pattern** for the last 3 weeks: when they usually arrive and
leave, where they spend most time, what they usually do, and how often they keep each routine.
Every evening (20:30, change it in **Activity & routines → How it works**) CAMS writes a short summary
of each person's day. (Since version 1.4 it no longer writes "changes from usual" notes every night,
to keep CAMS light.)

### Daily report

Open **Daily report**: for the chosen day it lists each person with first and last seen (and where),
the places they were, routines kept, late or missed, and notes. Filter by type or class, **Print** it
or **Download CSV** for Excel. **Write notes now** checks finished routines and writes the summaries
straight away. It is kept short so it opens fast, even with many people. Remember that routes are
deleted after 12 hours by default: for a full-day report, set *Routes* to 24 hours in **Settings →
Data and storage**.

### Ask CAMS (removed from the report page)

Version 1.4 removed the *Ask CAMS* box from the Daily report to keep it fast. It used to answer
questions typed in plain English, offline:

- *Who missed lunch today?* · *Who was late today?* · *Who was not seen today?*
- *Where was Godwill at 8:00 AM?* · *What was Godwill doing at 10:30 yesterday?*
- *Who was in the library this afternoon?* · *Who was using a phone today?* · *Godwill today*
