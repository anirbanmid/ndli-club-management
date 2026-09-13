import unittest
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

class TestKPIStackReminders(unittest.TestCase):
    """
    Test suite verifying the clutter-free KPI Card / Stack with red highlight
    and dedicated issue list modals in both Admin and Employee dashboards.
    """

    def test_admin_html_has_kpi_stack_and_modal_elements(self):
        admin_html = (BASE_DIR / "templates" / "admin.html").read_text(encoding="utf-8")
        
        # 1. Top KPI card with red highlight
        self.assertIn('id="card-admin-escalations"', admin_html)
        self.assertIn('kpi-admin-escalations', admin_html)
        
        # 2. In-page KPI stack card in #admin-issues-escalation-container
        self.assertIn('id="admin-issues-escalation-container"', admin_html)
        self.assertIn('admin-escalations-kpi-card', admin_html)
        self.assertIn('escalation-kpi-stack', admin_html)
        
        # 3. Dedicated Escalations List Modal
        self.assertIn('id="admin-escalations-list-modal"', admin_html)
        self.assertIn('id="admin-escalations-search-input"', admin_html)
        self.assertIn('id="admin-escalations-tbody"', admin_html)
        self.assertIn('id="admin-escalations-modal-count"', admin_html)
        
        # 4. JS Modal controller functions
        self.assertIn('openAdminEscalationsListModal', admin_html)
        self.assertIn('closeAdminEscalationsListModal', admin_html)
        self.assertIn('handleAdminEscalationsSearch', admin_html)
        self.assertIn('renderAdminEscalationsList', admin_html)
        self.assertIn('selectAdminEscalatedIssue', admin_html)

    def test_employee_html_has_kpi_stack_and_modal_elements(self):
        emp_html = (BASE_DIR / "templates" / "employee.html").read_text(encoding="utf-8")
        
        # 1. In-page KPI stack card in #employee-reminders-container
        self.assertIn('id="employee-reminders-container"', emp_html)
        self.assertIn('employee-reminders-kpi-card', emp_html)
        self.assertIn('employee-reminders-kpi-stack', emp_html)
        
        # 2. Dedicated Reminders List Modal
        self.assertIn('id="employee-reminders-list-modal"', emp_html)
        self.assertIn('id="employee-reminders-search-input"', emp_html)
        self.assertIn('id="employee-reminders-tbody"', emp_html)
        self.assertIn('id="employee-reminders-modal-count"', emp_html)
        
        # 3. JS Modal controller functions
        self.assertIn('openEmployeeRemindersListModal', emp_html)
        self.assertIn('closeEmployeeRemindersListModal', emp_html)
        self.assertIn('handleEmployeeRemindersSearch', emp_html)
        self.assertIn('renderEmployeeRemindersList', emp_html)
        self.assertIn('selectEmployeeReminder', emp_html)

if __name__ == "__main__":
    unittest.main()
