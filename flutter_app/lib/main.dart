
import 'dart:convert' show jsonDecode, jsonEncode;

import 'package:flutter/material.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

// Replace this with the main school computer's LAN IPv4 address.
// Android emulator: http://10.0.2.2:5000
// Physical device:   http://192.168.1.20:5000 (example only)
const String apiBaseUrl = 'http://10.0.2.2:5000';

void main() {
  WidgetsFlutterBinding.ensureInitialized();

  runApp(const YallaGoApp());
}

class YallaGoApp extends StatelessWidget {
  const YallaGoApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'YallaGo',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF344D7D),
        ),
        fontFamily: 'Arial',
      ),
      home: const LoginScreen(),
    );
  }
}

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final usernameController = TextEditingController();
  final passwordController = TextEditingController();
  final deviceCodeController = TextEditingController();

  bool hidePassword = true;
  bool loading = false;
  String? errorMessage;

  @override
  void dispose() {
    usernameController.dispose();
    passwordController.dispose();
    deviceCodeController.dispose();
    super.dispose();
  }

  Future<void> signIn() async {
    setState(() {
      loading = true;
      errorMessage = null;
    });

    try {
      final response = await http
          .post(
            Uri.parse('$apiBaseUrl/api/login'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({
              'username': usernameController.text.trim(),
              'password': passwordController.text,
              'device_code': deviceCodeController.text.trim(),
            }),
          )
          .timeout(const Duration(seconds: 10));

      final body = jsonDecode(response.body) as Map<String, dynamic>;

      if (response.statusCode != 200) {
        throw Exception(body['error'] ?? 'Unable to sign in.');
      }

      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('auth_token', body['token'] as String);
      await prefs.setString(
        'display_name',
        body['user']['display_name'] as String,
      );
      await prefs.setString('role', body['user']['role'] as String);
      await prefs.setString(
        'class_name',
        (body['user']['class_name'] ?? '') as String,
      );

      if (!mounted) return;
      Navigator.of(context).pushReplacement(
        MaterialPageRoute(builder: (_) => const HomeScreen()),
      );
    } catch (error) {
      setState(() {
        errorMessage = error.toString().replaceFirst('Exception: ', '');
      });
    } finally {
      if (mounted) {
        setState(() => loading = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFFF1F4F8),
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 430),
              child: Card(
                elevation: 2,
                color: Colors.white,
                child: Padding(
                  padding: const EdgeInsets.all(26),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Icon(
                        Icons.school_rounded,
                        size: 54,
                        color: Color(0xFF344D7D),
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'YallaGo',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 32,
                          fontWeight: FontWeight.bold,
                          color: Color(0xFF202A3C),
                        ),
                      ),
                      const SizedBox(height: 6),
                      const Text(
                        'School Attendance & Dismissal',
                        textAlign: TextAlign.center,
                        style: TextStyle(color: Colors.black54),
                      ),
                      const SizedBox(height: 30),
                      TextField(
                        controller: usernameController,
                        decoration: const InputDecoration(
                          labelText: 'Username',
                          prefixIcon: Icon(Icons.person_outline),
                          border: OutlineInputBorder(),
                        ),
                      ),
                      const SizedBox(height: 14),
                      TextField(
                        controller: passwordController,
                        obscureText: hidePassword,
                        decoration: InputDecoration(
                          labelText: 'Password',
                          prefixIcon: const Icon(Icons.lock_outline),
                          border: const OutlineInputBorder(),
                          suffixIcon: IconButton(
                            onPressed: () =>
                                setState(() => hidePassword = !hidePassword),
                            icon: Icon(
                              hidePassword
                                  ? Icons.visibility_off
                                  : Icons.visibility,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 14),
                      TextField(
                        controller: deviceCodeController,
                        decoration: const InputDecoration(
                          labelText: 'Registered device code',
                          helperText:
                              'Required for supervisors; administrator may leave it blank.',
                          prefixIcon: Icon(Icons.tablet_mac_outlined),
                          border: OutlineInputBorder(),
                        ),
                      ),
                      if (errorMessage != null) ...[
                        const SizedBox(height: 14),
                        Text(
                          errorMessage!,
                          style: const TextStyle(color: Colors.red),
                        ),
                      ],
                      const SizedBox(height: 22),
                      FilledButton(
                        onPressed: loading ? null : signIn,
                        style: FilledButton.styleFrom(
                          minimumSize: const Size.fromHeight(50),
                        ),
                        child: loading
                            ? const SizedBox(
                                width: 22,
                                height: 22,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Text('SIGN IN'),
                      ),
                      const SizedBox(height: 16),
                      const Text(
                        'PRIVATE SCHOOL NETWORK',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 10,
                          letterSpacing: 1.5,
                          color: Colors.black45,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  String displayName = '';
  String role = '';
  String className = '';

  @override
  void initState() {
    super.initState();
    loadUser();
  }

  Future<void> loadUser() async {
    final prefs = await SharedPreferences.getInstance();
    setState(() {
      displayName = prefs.getString('display_name') ?? '';
      role = prefs.getString('role') ?? '';
      className = prefs.getString('class_name') ?? '';
    });
  }

  Future<void> signOut() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('display_name');
    await prefs.remove('role');
    await prefs.remove('class_name');
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(
      MaterialPageRoute(builder: (_) => const LoginScreen()),
      (_) => false,
    );
  }

  @override
  Widget build(BuildContext context) {
    final isAdmin = role == 'admin';
    return Scaffold(
      appBar: AppBar(
        title: const Text('YallaGo'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            onPressed: signOut,
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: ListView(
        padding: const EdgeInsets.all(20),
        children: [
          Text(
            'Welcome, $displayName',
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 6),
          Text(
            isAdmin
                ? 'Administrator'
                : role == 'supervisor'
                    ? 'Class: $className'
                    : 'Reception',
            style: const TextStyle(color: Colors.black54),
          ),
          const SizedBox(height: 24),
          if (isAdmin) ...[
            const _FeatureTile(
              icon: Icons.manage_accounts_outlined,
              title: 'Employee Management',
              subtitle: 'Administrator-controlled accounts',
            ),
            const _FeatureTile(
              icon: Icons.devices_outlined,
              title: 'Device Management',
              subtitle: 'Register one device per supervisor',
            ),
            const _FeatureTile(
              icon: Icons.class_outlined,
              title: 'Class Management',
              subtitle: 'Create and organize school classes',
            ),
            const _FeatureTile(
              icon: Icons.groups_outlined,
              title: 'Student Management',
              subtitle: 'Register and assign students to classes',
            ),
            const _FeatureTile(
              icon: Icons.fact_check_outlined,
              title: 'Reports & Audit Log',
              subtitle: 'Attendance history and administrative actions',
            ),
          ] else if (role == 'supervisor') ...[
            const _FeatureTile(
              icon: Icons.how_to_reg_outlined,
              title: 'Morning Check-in',
              subtitle: 'Attendance for your assigned class',
            ),
            const _FeatureTile(
              icon: Icons.directions_walk_outlined,
              title: 'Dismissal Requests',
              subtitle: 'Prepare students for authorized pickup',
            ),
          ] else ...[
            const _FeatureTile(
              icon: Icons.search,
              title: 'Find Student',
              subtitle: 'Search and request student pickup',
            ),
            const _FeatureTile(
              icon: Icons.check_circle_outline,
              title: 'Confirm Handover',
              subtitle: 'Confirm student handover at the gate',
            ),
          ],
          const SizedBox(height: 18),
          const Text(
            'This is the expandable application shell. Feature screens will be connected to the secured API in the next development stage.',
            style: TextStyle(color: Colors.black54),
          ),
        ],
      ),
    );
  }
}

class _FeatureTile extends StatelessWidget {
  final IconData icon;
  final String title;
  final String subtitle;

  const _FeatureTile({
    required this.icon,
    required this.title,
    required this.subtitle,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      child: ListTile(
        leading: Icon(icon, color: const Color(0xFF344D7D), size: 30),
        title: Text(title),
        subtitle: Text(subtitle),
        trailing: const Icon(Icons.chevron_right),
      ),
    );
  }
}
