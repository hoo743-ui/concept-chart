# -*- coding: utf-8 -*-
"""llm.py : 로컬 LLM을 끼우는 자리 (표준 라이브러리만). 비용 없음, 대화 내용이 이 PC 밖으로 나가지 않는다.

    client = llm.make("ollama:qwen3:4b")      # "off"나 None이면 Off: 항상 사용 불가
    client.available()                         # 켜져 있고 모델이 있는가
    client.json(prompt, schema)                # 스키마에 맞는 dict. 실패하면 LLMError

지키는 것
- localhost 외의 주소로 보내지 않는다 (Host를 코드에서 고정).
- 한 번에 하나만 호출한다. CPU 스레드를 제한하고, 쓰고 나면 금방 메모리에서 내린다 (keep_alive).
- 다른 LLM을 쓰려면 available·json을 가진 클래스를 만들어 make에 더한다. 호출하는 쪽은 바뀌지 않는다.
"""
import json
import threading
import urllib.error
import urllib.request

OLLAMA = "http://127.0.0.1:11434"
NUM_THREAD = 2            # CPU 과부하 방지
NUM_CTX = 4096            # 입력을 짧게 유지해 메모리를 아낀다
KEEP_ALIVE = "60s"        # 쓰지 않으면 1분 뒤 GPU·메모리에서 내린다
TIMEOUT = 180


class LLMError(Exception):
    pass


class Off:
    name = "off"

    def available(self):
        return False

    def json(self, prompt, schema, max_tokens=400):
        raise LLMError("LLM이 꺼져 있습니다")


class Ollama:
    def __init__(self, model):
        self.model, self.name = model, "ollama:" + model
        self.lock = threading.Lock()

    def _post(self, path, body, timeout=TIMEOUT):
        req = urllib.request.Request(OLLAMA + path, json.dumps(body).encode("utf-8"), {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def available(self):
        try:
            with urllib.request.urlopen(OLLAMA + "/api/tags", timeout=2) as r:
                names = {m.get("name") for m in json.loads(r.read().decode("utf-8")).get("models", [])}
            return self.model in names
        except (OSError, ValueError):
            return False

    def json(self, prompt, schema, max_tokens=400):
        body = {"model": self.model, "prompt": prompt, "stream": False, "think": False, "format": schema, "keep_alive": KEEP_ALIVE,
                "options": {"temperature": 0, "seed": 42, "num_thread": NUM_THREAD, "num_ctx": NUM_CTX, "num_predict": max_tokens}}
        with self.lock:                                   # 한 번에 하나
            try:
                out = self._post("/api/generate", body)
            except (OSError, ValueError) as e:
                raise LLMError(f"{type(e).__name__}: {e}") from e
        try:
            got = json.loads(out["response"])
        except (KeyError, ValueError, TypeError) as e:
            raise LLMError("JSON이 아닌 응답") from e
        if not isinstance(got, dict) or any(k not in got for k in schema.get("required", [])):
            raise LLMError("스키마에 맞지 않는 응답")
        return got


def make(spec):
    if not spec or spec == "off":
        return Off()
    kind, _, model = spec.partition(":")
    if kind == "ollama" and model:
        return Ollama(model)
    raise ValueError(f"알 수 없는 LLM: {spec} (예: ollama:qwen3:4b, off)")
