import unittest
import requests
import os
import tempfile
from datetime import datetime
from config import get_config

class FileUploadCenterTests(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        self.base_url = f"http://{self.config.SERVER_HOST}:{self.config.PORT}"
        self.session = requests.Session()
        self.test_file_path = None
        self.user_id = "test_user"

    def tearDown(self):
        self.session.close()
        if self.test_file_path and os.path.exists(self.test_file_path):
            os.remove(self.test_file_path)

    def test_01_health_check(self):
        """Test the health check endpoint"""
        response = self.session.get(f"{self.base_url}/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["server"], "running")

    def test_02_upload_file(self):
        """Test file upload"""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n%Test PDF\n")
            self.test_file_path = f.name
        files = {"file": open(self.test_file_path, "rb")}
        data = {"file_location": self.config.UPLOAD_BASE_DIR}
        headers = {"X-User-Id": self.user_id}
        response = self.session.post(f"{self.base_url}/api/upload", files=files, data=data, headers=headers)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn("upload_id", data["data"])
        self.upload_id = data["data"]["upload_id"]
        self.uploaded_filename = data["data"]["filename"]

    def test_03_invalid_file_type(self):
        """Test uploading an invalid file type"""
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
            f.write(b"Test text file")
            self.test_file_path = f.name
        files = {"file": open(self.test_file_path, "rb")}
        data = {"file_location": self.config.UPLOAD_BASE_DIR}
        headers = {"X-User-Id": self.user_id}
        response = self.session.post(f"{self.base_url}/api/upload", files=files, data=data, headers=headers)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "Invalid file type")

    def test_04_missing_user_id(self):
        """Test uploading without X-User-Id header"""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4\n%Test PDF\n")
            self.test_file_path = f.name
        files = {"file": open(self.test_file_path, "rb")}
        data = {"file_location": self.config.UPLOAD_BASE_DIR}
        response = self.session.post(f"{self.base_url}/api/upload", files=files, data=data)
        self.assertEqual(response.status_code, 401)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "Missing user ID in headers")

    def test_05_list_uploads(self):
        """Test listing uploads with filters"""
        self.test_02_upload_file()
        today = datetime.now().strftime("%Y-%m-%d")
        headers = {"X-User-Id": self.user_id}
        response = self.session.get(f"{self.base_url}/api/uploads?from_date={today}&to_date={today}&search={self.uploaded_filename}", headers=headers)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertTrue(len(data["data"]) > 0)
        self.assertEqual(data["data"][0]["filename"], self.uploaded_filename)

    def test_06_invalid_date_filter(self):
        """Test listing with invalid date filter"""
        headers = {"X-User-Id": self.user_id}
        response = self.session.get(f"{self.base_url}/api/uploads?from_date=2025-08-08&to_date=2025-08-07", headers=headers)
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "From date cannot be after to date")

    def test_07_share_file(self):
        """Test sharing a file"""
        self.test_02_upload_file()
        second_user = "test_user2"
        headers = {"X-User-Id": self.user_id}
        response = self.session.post(
            f"{self.base_url}/api/share/{self.upload_id}",
            json={"shared_with": second_user},
            headers=headers
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertIn(f"Shared upload {self.upload_id}", data["message"])

    def test_08_download_file(self):
        """Test downloading a file"""
        self.test_02_upload_file()
        headers = {"X-User-Id": self.user_id}
        response = self.session.get(f"{self.base_url}/api/download/{self.uploaded_filename}", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn("application/pdf", response.headers["Content-Type"])
        response = self.session.get(f"{self.base_url}/api/uploads", headers=headers)
        data = response.json()
        self.assertEqual(data["data"][0]["download_count"], 1)

    def test_09_unauthorized_download(self):
        """Test downloading a file without access"""
        self.test_02_upload_file()
        other_user = "unauthorized_user"
        headers = {"X-User-Id": other_user}
        response = self.session.get(f"{self.base_url}/api/download/{self.uploaded_filename}", headers=headers)
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertEqual(data["message"], "File not accessible")

if __name__ == "__main__":
    unittest.main()