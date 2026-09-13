"""
Unit tests for Authentication, Password Hashing, Role Authorization, and Session Management.
"""
import unittest
from auth import AuthService, hash_password, verify_password
from config import (
    DEFAULT_ADMIN_EMAIL,
    DEFAULT_ADMIN_PASSWORD,
    INITIAL_EMPLOYEES
)
from init_db import initialize_database

class TestAuth(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        initialize_database()

    def test_password_hashing(self):
        pwd = "TestSecretPassword123!"
        h, salt = hash_password(pwd)
        self.assertTrue(verify_password(pwd, h, salt))
        self.assertFalse(verify_password("WrongPassword", h, salt))

    def test_admin_login(self):
        success, err, session = AuthService.authenticate(DEFAULT_ADMIN_EMAIL, DEFAULT_ADMIN_PASSWORD)
        self.assertTrue(success)
        self.assertIsNone(err)
        self.assertIsNotNone(session)
        self.assertEqual(session["role"], "ADMIN")
        self.assertEqual(session["email"], DEFAULT_ADMIN_EMAIL)

        # Validate session token
        validated = AuthService.validate_session(session["token"])
        self.assertIsNotNone(validated)
        self.assertEqual(validated["user_id"], session["user_id"])

        # Logout
        AuthService.logout(session["token"])
        self.assertIsNone(AuthService.validate_session(session["token"]))

    def test_employee_login(self):
        emp = INITIAL_EMPLOYEES[0]
        success, err, session = AuthService.authenticate(emp["email"], emp["password"])
        self.assertTrue(success)
        self.assertIsNone(err)
        self.assertIsNotNone(session)
        self.assertEqual(session["role"], "EMPLOYEE")
        self.assertEqual(session["zone"], "North")

    def test_employee_login_with_user_id(self):
        emp = INITIAL_EMPLOYEES[0]
        # Test with uppercase User ID
        success, err, session = AuthService.authenticate(emp["id"], emp["password"])
        self.assertTrue(success)
        self.assertIsNone(err)
        self.assertIsNotNone(session)
        self.assertEqual(session["user_id"], emp["id"])
        self.assertEqual(session["role"], "EMPLOYEE")

        # Test with lowercase User ID
        success2, err2, session2 = AuthService.authenticate(emp["id"].lower(), emp["password"])
        self.assertTrue(success2)
        self.assertIsNotNone(session2)

        # Test with leading/trailing spaces
        success3, _, session3 = AuthService.authenticate(f"  {emp['id']}  ", emp["password"])
        self.assertTrue(success3)
        self.assertIsNotNone(session3)

    def test_admin_login_with_user_id(self):
        success, err, session = AuthService.authenticate("ADMIN01", DEFAULT_ADMIN_PASSWORD)
        self.assertTrue(success)
        self.assertIsNone(err)
        self.assertEqual(session["role"], "ADMIN")

        success2, _, session2 = AuthService.authenticate("admin01", DEFAULT_ADMIN_PASSWORD)
        self.assertTrue(success2)
        self.assertEqual(session2["role"], "ADMIN")

    def test_invalid_credentials(self):
        success, err, session = AuthService.authenticate("nonexistent@ndli.edu.in", "any")
        self.assertFalse(success)
        self.assertIn("Invalid email or password", err)

        success2, err2, _ = AuthService.authenticate(DEFAULT_ADMIN_EMAIL, "WrongPassword")
        self.assertFalse(success2)

    def test_blocked_employee_login(self):
        emp = INITIAL_EMPLOYEES[1]
        emp_id = emp["id"]

        # Block user
        AuthService.set_user_status(emp_id, is_active=False)

        # Attempt login
        success, err, _ = AuthService.authenticate(emp["email"], emp["password"])
        self.assertFalse(success)
        self.assertIn("blocked", err.lower())

        # Unblock user
        AuthService.set_user_status(emp_id, is_active=True)
        success_after, _, _ = AuthService.authenticate(emp["email"], emp["password"])
        self.assertTrue(success_after)

if __name__ == "__main__":
    unittest.main()
