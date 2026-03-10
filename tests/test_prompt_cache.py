import unittest

from app.services import prompt_cache


class FakeRedis:
    def __init__(self):
        self.kv = {}
        self.zsets = {}

    def ping(self):
        return True

    def get(self, key):
        return self.kv.get(key)

    def set(self, key, value, ex=None):
        self.kv[key] = value
        return True

    def expire(self, key, ttl):
        return True

    def zadd(self, key, mapping):
        zset = self.zsets.setdefault(key, {})
        zset.update(mapping)
        return True

    def zrevrange(self, key, start, end):
        zset = self.zsets.get(key, {})
        ordered = sorted(zset.items(), key=lambda x: x[1], reverse=True)
        members = [member for member, _ in ordered]
        if end < 0:
            return members[start:]
        return members[start:end + 1]

    def zremrangebyscore(self, key, min_score, max_score):
        zset = self.zsets.get(key, {})
        to_remove = [member for member, score in zset.items() if min_score <= score <= max_score]
        for member in to_remove:
            del zset[member]
        return len(to_remove)


class PromptCacheTests(unittest.TestCase):
    def setUp(self):
        self.fake_redis = FakeRedis()
        self.original_get_redis = prompt_cache.get_redis_client
        prompt_cache.get_redis_client = lambda: self.fake_redis

        self.original_settings = {
            "CACHE_ENABLED": prompt_cache.settings.CACHE_ENABLED,
            "CACHE_EXACT_TTL_SEC": prompt_cache.settings.CACHE_EXACT_TTL_SEC,
            "CACHE_SEMANTIC_TTL_SEC": prompt_cache.settings.CACHE_SEMANTIC_TTL_SEC,
            "CACHE_COOLDOWN_SEC": prompt_cache.settings.CACHE_COOLDOWN_SEC,
            "CACHE_SIMILARITY_THRESHOLD": prompt_cache.settings.CACHE_SIMILARITY_THRESHOLD,
            "CACHE_MAX_CANDIDATES": prompt_cache.settings.CACHE_MAX_CANDIDATES,
        }

        prompt_cache.settings.CACHE_ENABLED = True
        prompt_cache.settings.CACHE_EXACT_TTL_SEC = 300
        prompt_cache.settings.CACHE_SEMANTIC_TTL_SEC = 180
        prompt_cache.settings.CACHE_COOLDOWN_SEC = 15
        prompt_cache.settings.CACHE_SIMILARITY_THRESHOLD = 0.4
        prompt_cache.settings.CACHE_MAX_CANDIDATES = 20

    def tearDown(self):
        prompt_cache.get_redis_client = self.original_get_redis
        for key, value in self.original_settings.items():
            setattr(prompt_cache.settings, key, value)

    def test_context_fingerprint_is_stable(self):
        a = prompt_cache.build_context_fingerprint(
            platform="telegram",
            user_id="u1",
            role="customer",
            message_text="How much is jollof?",
            menu_text="- Jollof: N500",
            model_identifier="model-a",
        )
        b = prompt_cache.build_context_fingerprint(
            platform="telegram",
            user_id="u1",
            role="customer",
            message_text="How much is jollof?",
            menu_text="- Jollof: N500",
            model_identifier="model-a",
        )
        c = prompt_cache.build_context_fingerprint(
            platform="telegram",
            user_id="u1",
            role="customer",
            message_text="How much is jollof?",
            menu_text="- Jollof: N700",
            model_identifier="model-a",
        )
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_exact_cache_roundtrip(self):
        ok = prompt_cache.store_cached_reply(
            platform="telegram",
            user_id="u1",
            role="customer",
            message_text="hello",
            menu_text="- Jollof: N500",
            model_identifier="model-a",
            intent="greeting",
            reply_text="Hello customer",
        )
        self.assertTrue(ok)
        hit = prompt_cache.get_exact_cached_reply(
            platform="telegram",
            user_id="u1",
            role="customer",
            message_text="hello",
            menu_text="- Jollof: N500",
            model_identifier="model-a",
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["reply"], "Hello customer")

    def test_semantic_cache_hit_for_paraphrase(self):
        prompt_cache.store_cached_reply(
            platform="telegram",
            user_id="u1",
            role="customer",
            message_text="how much is jollof rice",
            menu_text="- Jollof Rice: N500",
            model_identifier="model-a",
            intent="inquiry",
            reply_text="Jollof na N500",
        )
        semantic_hit = prompt_cache.get_semantic_cached_reply(
            platform="telegram",
            user_id="u1",
            role="customer",
            message_text="price of jollof rice",
            menu_text="- Jollof Rice: N500",
            model_identifier="model-a",
        )
        self.assertIsNotNone(semantic_hit)
        self.assertEqual(semantic_hit["reply"], "Jollof na N500")

    def test_non_cacheable_intent_not_stored(self):
        ok = prompt_cache.store_cached_reply(
            platform="telegram",
            user_id="u1",
            role="customer",
            message_text="add two coke",
            menu_text="- Coke: N500",
            model_identifier="model-a",
            intent="ordering",
            reply_text="I don add am",
        )
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
