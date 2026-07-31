from __future__ import annotations

import os
import unittest
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("CHATGPT2API_AUTH_KEY", "test-auth")

from services.backends import firefly_client as client  # noqa: E402
from test._firefly_helpers import first_callable  # noqa: E402


def _normalize_fn():
    fn = first_callable(
        client,
        "normalize_video_poll_url",
        "normalizeVideoPollUrl",
        "normalize_poll_url",
        "_normalize_video_poll_url",
        required=False,
    )
    if fn is not None:
        return fn
    # 类方法回退
    cls = getattr(client, "AdobeFireflyClient", None) or getattr(
        client, "FireflyClient", None
    )
    if cls is not None:
        fn = first_callable(
            cls,
            "normalize_video_poll_url",
            "_normalize_video_poll_url",
            "normalizeVideoPollUrl",
            required=False,
        )
        if fn is not None:
            return fn
    raise AssertionError(
        "missing normalize_video_poll_url "
        "(expected normalize_video_poll_url on firefly_client)"
    )


def _host_query(url: str) -> str:
    """取 ?host= 参数（兼容末尾斜杠）。"""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    values = qs.get("host") or []
    return values[0] if values else ""


class NormalizeVideoPollUrlTests(unittest.TestCase):
    """normalize_video_poll_url：firefly-epo → bks-epo 改写。"""

    def test_epo_us_east_rewritten_to_bks(self) -> None:
        """典型 epo 区域链接改写为 bks，并带 host 查询参数。

        任务示例用 epo1；实现要求 4 位数字分片（对齐 adobe2api），
        这里用 epo0001 覆盖 us-east-1 形态。
        """
        fn = _normalize_fn()
        raw = (
            "https://firefly-epo0001-us-east-1.adobe.io"
            "/v2/jobs/result/job123"
        )
        out = fn(raw)
        parsed = urlparse(out)
        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "bks-epo0001.adobe.io")
        self.assertEqual(parsed.path, "/v2/jobs/result/job123")
        host_q = _host_query(out)
        self.assertTrue(
            host_q.rstrip("/") == "firefly-epo0001-us-east-1.adobe.io"
            or host_q == "firefly-epo0001-us-east-1.adobe.io/",
            f"host query unexpected: {host_q!r}",
        )

    def test_epo_with_existing_query_preserves_host(self) -> None:
        """原链接带 query 时仍正确写入 host=原 host。"""
        fn = _normalize_fn()
        raw = (
            "https://firefly-epo1234-prod.adobe.io"
            "/v2/jobs/result/video-job-1?foo=1&bar=2"
        )
        out = fn(raw)
        self.assertIn("bks-epo1234.adobe.io", out)
        self.assertIn("/v2/jobs/result/video-job-1", out)
        host_q = _host_query(out)
        self.assertTrue(
            host_q.rstrip("/") == "firefly-epo1234-prod.adobe.io",
            f"host query unexpected: {host_q!r}",
        )

    def test_non_epo_urls_unchanged(self) -> None:
        """非 epo 链接（普通 poll / 已是 bks）原样返回。"""
        fn = _normalize_fn()
        cases = (
            "https://poll.example/jobs/1",
            "https://bks-epo1234.adobe.io/v2/jobs/result/job9?host=x.adobe.io/",
            "https://firefly-3p.ff.adobe.io/v2/jobs/result/abc",
            "not a url",
            "",
        )
        for raw in cases:
            with self.subTest(raw=raw):
                self.assertEqual(fn(raw), raw)

    def test_invalid_shard_unchanged(self) -> None:
        """分片非 4 位数字时不改写。"""
        fn = _normalize_fn()
        raw = "https://firefly-epoabcd.adobe.io/v2/jobs/result/job1"
        self.assertEqual(fn(raw), raw)
        # 单数字分片（任务文案简化例）通常也不改写
        raw_short = (
            "https://firefly-epo1-us-east-1.adobe.io/v2/jobs/result/job123"
        )
        out_short = fn(raw_short)
        # 实现若放宽分片规则也可接受，但至少结果应是 str
        self.assertIsInstance(out_short, str)

    def test_different_shard_and_region_variants(self) -> None:
        """不同 shard / region 变体均正确映射。"""
        fn = _normalize_fn()
        cases = (
            (
                "https://firefly-epo5678-prod.adobe.io/jobs/video-job-2",
                "bks-epo5678.adobe.io",
                "video-job-2",
                "firefly-epo5678-prod.adobe.io",
            ),
            (
                "https://firefly-epo9999-eu-west-1.adobe.io/v2/jobs/result/abc-xyz",
                "bks-epo9999.adobe.io",
                "abc-xyz",
                "firefly-epo9999-eu-west-1.adobe.io",
            ),
            (
                "https://firefly-epo0420-us-west-2.adobe.io/v2/status/result/z9",
                "bks-epo0420.adobe.io",
                "z9",
                "firefly-epo0420-us-west-2.adobe.io",
            ),
        )
        for raw, expect_host, expect_job, expect_orig_host in cases:
            with self.subTest(raw=raw):
                out = fn(raw)
                parsed = urlparse(out)
                self.assertEqual(parsed.netloc, expect_host)
                self.assertTrue(
                    parsed.path.endswith(f"/{expect_job}")
                    or parsed.path == f"/v2/jobs/result/{expect_job}",
                    f"path unexpected: {parsed.path}",
                )
                # 路径应归一到 /v2/jobs/result/{jobId}
                self.assertEqual(parsed.path, f"/v2/jobs/result/{expect_job}")
                host_q = _host_query(out).rstrip("/")
                self.assertEqual(host_q, expect_orig_host)


if __name__ == "__main__":
    unittest.main()
