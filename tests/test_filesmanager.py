import os.path
import unittest
from io import BytesIO
from time import time
from unittest.mock import Mock, PropertyMock, patch

from xero import Xero
from xero.auth import OAuth2Credentials
from xero.exceptions import XeroForbidden, XeroTenantIdNotSet


class FilesManagerTest(unittest.TestCase):
    def setUp(self):
        super().setUp()
        # Create an expired token to be used by tests
        self.expired_token = {
            "access_token": "1234567890",
            "expires_in": 1800,
            "token_type": "Bearer",
            "refresh_token": "0987654321",
            "expires_at": time(),
        }

        self.filepath = "test_file.txt"
        with open(self.filepath, "w") as f:
            f.write("test")

    def tearDown(self):
        os.remove(self.filepath)

    @patch("requests.get")
    def test_tenant_is_used_in_xero_request(self, r_get):
        credentials = OAuth2Credentials(
            "client_id", "client_secret", token=self.expired_token, tenant_id="12345"
        )
        xero = Xero(credentials)
        r_get.return_value = Mock(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
        )
        xero.filesAPI.files.all()

        self.assertEqual(r_get.call_args[1]["headers"]["Xero-tenant-id"], "12345")

    @patch("requests.post")
    def test_upload_file_as_path(self, r_get):
        credentials = OAuth2Credentials(
            "client_id", "client_secret", token=self.expired_token, tenant_id="12345"
        )
        xero = Xero(credentials)
        r_get.return_value = Mock(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
        )

        def inspect_upload(*args, **kwargs):
            handle = kwargs["files"][self.filepath]
            self.assertFalse(handle.closed)
            self.assertEqual(handle.read(), b"test")
            return r_get.return_value

        r_get.side_effect = inspect_upload
        xero.filesAPI.files.upload_file(path=self.filepath)

        self.assertIn(self.filepath, r_get.call_args[1]["files"])
        handle = r_get.call_args[1]["files"][self.filepath]
        try:
            self.assertTrue(handle.closed)
        finally:
            handle.close()

    def test_path_upload_closes_its_handle_at_each_failure_stage(self):
        for stage in ("tenant", "credentials", "request", "response", "json"):
            with self.subTest(stage=stage):
                credentials = OAuth2Credentials(
                    "client_id",
                    "client_secret",
                    token=self.expired_token,
                    tenant_id=None if stage == "tenant" else "12345",
                )
                xero = Xero(credentials)
                response = Mock(
                    status_code=403 if stage == "response" else 200,
                    headers={"content-type": "application/json"},
                )
                response.json.side_effect = RuntimeError("invalid response")
                expected = (
                    XeroTenantIdNotSet
                    if stage == "tenant"
                    else (XeroForbidden if stage == "response" else RuntimeError)
                )
                with (
                    open(self.filepath, "rb") as handle,
                    patch(
                        "xero.filesmanager.open", return_value=handle, create=True
                    ) as opener,
                    patch("requests.post", return_value=response) as post,
                    patch.object(
                        OAuth2Credentials, "oauth", new_callable=PropertyMock
                    ) as oauth,
                ):
                    if stage == "credentials":
                        oauth.side_effect = RuntimeError("credentials unavailable")
                    if stage == "request":
                        post.side_effect = RuntimeError("request failed")
                    with self.assertRaises(expected):
                        xero.filesAPI.files.upload_file(self.filepath)
                    if stage in ("tenant", "credentials"):
                        post.assert_not_called()
                    opener.assert_called_once_with(self.filepath, mode="rb")
                    self.assertTrue(handle.closed)

    def test_supplied_stream_stays_open_after_success_or_failure(self):
        credentials = OAuth2Credentials(
            "client_id", "client_secret", token=self.expired_token, tenant_id="12345"
        )
        xero = Xero(credentials)
        for failed in (False, True):
            with (
                self.subTest(failed=failed),
                BytesIO(b"supplied") as stream,
                patch("requests.post") as post,
            ):
                post.return_value = Mock(status_code=204)
                if failed:
                    post.side_effect = RuntimeError("request failed")
                    with self.assertRaises(RuntimeError):
                        xero.filesAPI.files.upload_file(
                            filename="supplied.txt", file=stream
                        )
                else:
                    xero.filesAPI.files.upload_file(
                        filename="supplied.txt", file=stream
                    )
                self.assertIs(post.call_args.kwargs["files"]["supplied.txt"], stream)
                self.assertFalse(stream.closed)

    def test_path_takes_precedence_and_keeps_the_folder_destination(self):
        credentials = OAuth2Credentials(
            "client_id", "client_secret", token=self.expired_token, tenant_id="12345"
        )
        xero = Xero(credentials)
        with BytesIO(b"supplied") as stream, patch("requests.post") as post:
            post.return_value = Mock(status_code=204)
            xero.filesAPI.files.upload_file(
                self.filepath, "folder-id", "ignored.txt", stream
            )
            self.assertTrue(post.call_args.args[0].endswith("/Files/folder-id"))
            self.assertEqual(list(post.call_args.kwargs["files"]), [self.filepath])
            handle = post.call_args.kwargs["files"][self.filepath]
            try:
                self.assertTrue(handle.closed)
                self.assertFalse(stream.closed)
                self.assertEqual(stream.tell(), 0)
            finally:
                handle.close()

    @patch("requests.post")
    def test_upload_file_as_file(self, r_get):
        credentials = OAuth2Credentials(
            "client_id", "client_secret", token=self.expired_token, tenant_id="12345"
        )
        xero = Xero(credentials)
        r_get.return_value = Mock(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
        )

        with open(self.filepath) as f:
            xero.filesAPI.files.upload_file(
                file=f, filename=os.path.basename(self.filepath)
            )

        self.assertIn(self.filepath, r_get.call_args[1]["files"])
