# Privacy and responsible use

CAMS processes **biometric data** (face prints) and location records of identifiable people.
In Tanzania this is sensitive personal data under the Personal Data Protection Act, 2022; most
other countries have similar laws. The organisation that runs CAMS is responsible for using it
lawfully. This page lists what CAMS does to help, and what you must do.

## What CAMS does

- **Stays local.** Video, faces and records are processed and stored only on the CAMS PC
  (`%APPDATA%\CAMS`). Nothing is sent to TransitTech or to the internet.
- **Blurs strangers.** Faces of people who are not enrolled are blurred in the live view and in
  saved pictures (setting on by default). Strangers are only logged on cameras marked
  *Restricted area*.
- **Records consent** per person: whether consent was given, by whom and when.
- **Deletes old records** automatically after the number of days set in Settings (30 by default).
- **Erases a person completely** (Delete person and data): face prints, pictures and all sightings.
- **Inactive people** are no longer recognised but their record is kept until deleted.
- **Limits access** with personal accounts and three roles, and **logs** every sign-in, search,
  enrolment, change, export and deletion in the activity log.
- **Stores passwords** only as salted PBKDF2 hashes. Camera passwords are hidden in the interface.

## What you must do

1. **Have a clear, written purpose** (for example campus safety) and do not use CAMS for anything else.
2. **Get informed consent** before enrolling anyone. For students under 18, from a parent or guardian.
   Let people refuse; do not enrol people who refuse.
3. **Put up signs** at entrances saying that cameras with face recognition are in use, who runs
   them, and whom to contact.
4. **Register as a data controller** with the Personal Data Protection Commission where the law requires it.
5. **Give accounts only to staff who need them**, with the lowest role that works. Review the
   activity log regularly.
6. **Never act on a match alone.** A match is a lead to check with your own eyes, not proof.
   Face recognition makes mistakes, more often in poor light, at angles, and with people who
   look alike.
7. **Answer requests** from people who want to see or erase their data. Use *Delete person and
   data* for erasure.
8. **Protect the PC:** Windows password, BitLocker disk encryption, locked room, updates, and keep
   backups encrypted and locked away.
9. **Keep records only as long as needed** and set the retention days to match.
