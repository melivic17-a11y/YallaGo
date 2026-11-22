# YallaGo – Starter Source Code (v0.2)

This is a clean, expandable starter project for the YallaGo school attendance and dismissal system.

## Included in this version

- Flutter mobile application shell with a login screen and role-aware landing screen.
- Flask + SQLite local-network backend.
- Password hashing and signed login tokens.
- Central administrator-only endpoints for creating and listing classes, employees, students, and devices.
- One registered device per supervisor account.
- A device is labelled by its assigned class name, not by the supervisor's name.
- Multiple supervisors/devices may be assigned to the same class.
- Attendance and dismissal event tables.
- Administrative audit log.
- Deactivation fields so historical attendance can be retained.

## Important: this is a development foundation, not a finished production system

The first version deliberately establishes the project structure and core data rules. It does not yet include every screen, parent pickup workflow, push notifications, router configuration, production HTTPS, backups, or full reporting.

### Architecture

- Flutter app: `flutter_app/`
- Local school server: `backend/`
- SQLite database is stored on the computer running the backend.
- Other devices connect to the backend computer over the school's Wi-Fi/LAN.

**Wi-Fi access control and YallaGo authorization are separate.** This backend controls YallaGo access. Allowing or blocking devices from joining Wi-Fi itself must be configured on a compatible router/access point, or through its management API if supported. The app does not automatically configure the router.

## 1. Start the backend on the main school computer

Install Python 3.11 or newer.

Open a terminal in the `backend` folder:

```bash
python -m venv .venv
```

Windows Git Bash:

```bash
source .venv/Scripts/activate
```

Windows Command Prompt:

```bat
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Create the first administrator:

```bash
python app.py --create-admin
```

The program asks for the administrator username and password. Do not use a sample or shared password.

Start the server:

```bash
python app.py
```

The server listens on port `5000`. For a first local test, open:

`http://127.0.0.1:5000/api/health`

To connect phones/tablets, find the main computer's local IPv4 address (for example `192.168.1.20`) and set that address in the Flutter app's API configuration. The computer and devices must be on the same trusted school network. Allow Python through Windows Firewall only on the private school network.

## 2. Configure the Flutter app

Install Flutter, then generate the native platform folders from the included Flutter source:

```bash
cd flutter_app
flutter create --platforms=android,ios,windows .
flutter pub get
flutter run
```

If Flutter asks whether to overwrite the existing `lib/main.dart` or `pubspec.yaml`, keep the included YallaGo versions. After platform generation, Android's local-development manifest may need `android:usesCleartextTraffic="true"` on the `<application>` element to permit local HTTP. This is development-only; production should use HTTPS.

In `lib/main.dart`, change `apiBaseUrl` to the main computer's local IP address:

```dart
const String apiBaseUrl = 'http://192.168.1.20:5000';
```

For Android Emulator, use `http://10.0.2.2:5000` to reach the host computer.

For a physical Android device, use the main computer's LAN IPv4 address.

Android development note: local HTTP may be blocked by Android cleartext-traffic policy. This starter includes a development manifest setting to permit local HTTP. Do not use that setting for a public production deployment; configure HTTPS first.

## 3. Create classes and users

The backend exposes administrator endpoints. Authenticate as the administrator, then send the returned token in:

`Authorization: Bearer YOUR_TOKEN`

Endpoints:
- `GET /api/admin/classes`
- `POST /api/admin/classes` – JSON: `{"name":"Grade 1 - A"}`
- `GET /api/admin/employees`
- `POST /api/admin/employees` – JSON: `{"username":"supervisor1","password":"...","display_name":"Supervisor 1","role":"supervisor"}`
- `GET /api/admin/students`
- `POST /api/admin/students` – JSON: `{"student_number":"1001","full_name":"Student Name","class_id":1}`
- `GET /api/admin/devices`
- `POST /api/admin/devices` – JSON: `{"device_code":"DEVICE-001","employee_id":2,"class_id":1}`
- `PATCH /api/admin/classes/1` – rename or deactivate a class, e.g. `{"is_active":false}`
- `PATCH /api/admin/employees/2` – edit employee details or deactivate an account
- `PATCH /api/admin/students/10` – edit, transfer, or deactivate a student
- `PATCH /api/admin/devices/1` – reassign, replace device code, or deactivate a device

Use `is_active: false` to remove/deactivate records while preserving attendance history. Permanent deletion is intentionally not provided in this foundation.

Device registration rules:
- A supervisor may have only one active device.
- A device may be assigned to only one supervisor.
- Several supervisors/devices may be assigned to the same class.
- The device label returned by the API is the class name.
- Only an administrator can register or reassign devices.
- Supervisors cannot add or remove employees, students, classes, or devices.

The current API is intentionally small. The next development stage should add secure edit/deactivate/reassign screens and endpoints, attendance workflow screens, parent pickup requests, and reports.

## 4. Data protection

- Keep the database file and backups on the main school computer.
- Do not delete attendance history when an employee, student, class, or device is deactivated.
- Restrict Windows access to the database and backup folder.
- Do not expose port 5000 to the public internet.
- Before real student data is entered, add HTTPS, scheduled backups, restore testing, stronger device enrollment, rate limiting, and a security review.

## Project structure

```text
YallaGo_Starter_v0_2/
├── README.md
├── backend/
│   ├── app.py
│   └── requirements.txt
└── flutter_app/
    ├── pubspec.yaml
    ├── android/app/src/main/AndroidManifest.xml
    └── lib/main.dart
```
