"""Capability-negotiated completion transport, with per-receipt acknowledgement."""
import json
import urllib.error


class CompletionTransport:
    def __init__(self, get, post):
        self.get, self.post = get, post
        self.capabilities = None

    def send(self, items):
        if self.capabilities is None:
            try:
                capabilities = self.get('/api/capabilities')
            except urllib.error.HTTPError as error:
                if error.code not in (404, 405):
                    raise
                capabilities = {}
            if not isinstance(capabilities, dict):
                raise ValueError('Invalid coordinator capabilities')
            self.capabilities = capabilities
        capabilities = self.capabilities
        if capabilities.get('batch_completions') is not True:
            payload = items[0]
            return [(payload['lease_id'], self.post('/api/complete', payload))]
        count = capabilities.get('max_completion_count', 1)
        limit = capabilities.get('max_body_bytes', 262144)
        if type(count) is not int or not 1 <= count <= 8 or type(limit) is not int or limit <= 0:
            raise ValueError('Invalid coordinator batch limits')
        batch = []
        for payload in items[:count]:
            # Match worker.post's compact, ASCII-escaped JSON serialization.
            candidate = batch + [payload]
            if len(json.dumps({'submissions': candidate},separators=(',',':')).encode('utf-8')) > limit:
                break
            batch = candidate
        if not batch:
            raise ValueError('Saved receipt exceeds coordinator body limit; retained')
        try:
            reply = self.post('/api/completions', {'submissions': batch})
        except urllib.error.HTTPError as error:
            if error.code not in (404, 405):
                raise
            self.capabilities = {}
            return self.send(items)
        results = reply.get('results') if isinstance(reply, dict) else None
        expected = {item['lease_id'] for item in batch}
        if not isinstance(results, list) or len(results) != len(batch):
            raise ValueError('Incomplete batch acknowledgement; receipts retained')
        seen = set()
        for item in results:
            if not isinstance(item, dict) or item.get('lease_id') not in expected or item['lease_id'] in seen:
                raise ValueError('Invalid batch acknowledgement; receipts retained')
            if type(item.get('status')) is not int or not isinstance(item.get('result'), dict):
                raise ValueError('Invalid batch result; receipts retained')
            seen.add(item['lease_id'])
        # Validate the entire envelope before allowing any acknowledgement.
        return [(item['lease_id'], item['result'] if 200 <= item['status'] < 300
                 else {'ok': False, 'status': item['status']}) for item in results]
