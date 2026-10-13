"""Context-dependent Responses provider double; no inference or network access."""

import json
import re
from datetime import UTC, datetime

import httpx

from ai_agent_lab.mail.infrastructure.inmemory.dataset import MailDatasetLoader
from ai_agent_lab.mail.infrastructure.inmemory.mail_tools import Mailbox


def bounded_mailbox(root):
    """Re-date controlled sample messages, keeping two out-of-period sentinels."""
    sample = MailDatasetLoader().load_file(root / "data" / "mail" / "sample_mailbox.json")["local-user"]
    templates = (sample.message("m-alpha-1"), sample.message("m-invoice-1"), sample.message("m-newsletter-1"))
    messages = [
        templates[index % 3].model_copy(update={
            "message_id": f"controlled-{index:02}",
            "thread_id": f"controlled-thread-{index:02}",
            "sent_at": datetime(2026, 10, 4 + index % 7, 12, tzinfo=UTC),
            "label_ids": ("INBOX",),
        })
        for index in range(15)
    ]
    for day in (3, 11):
        messages.append(templates[0].model_copy(update={
            "message_id": f"outside-{day}", "sent_at": datetime(2026, 10, day, 12, tzinfo=UTC),
            "label_ids": ("INBOX",),
        }))
    return Mailbox("local-user", messages, sample.labels)


class ContextualResponsesProvider:
    """Derive follow-up calls exclusively from the stored first-turn table.

    This deterministic model double exercises actual SDK serialization and
    provider history, not natural-language interpretation by a real LLM.
    """

    def __init__(self):
        self.requests = []
        self.histories = {}
        self.effective_histories = []

    def __call__(self, request):
        body = json.loads(request.content)
        previous = body.get("previous_response_id")
        history = [*self.histories.get(previous, []), *body["input"]]
        self.requests.append(body)
        self.effective_histories.append(history)
        output = self._decide(history)
        index = len(self.requests)
        response = {
            "id": f"resp_scope_{index}", "object": "response", "created_at": 1,
            "model": "controlled-model", "status": "completed", "output": output,
            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
        }
        self.histories[response["id"]] = [*history, *output]
        if not body.get("stream"):
            return httpx.Response(200, json=response)
        return self._stream(response)

    def _decide(self, history):
        users = [item for item in history if item.get("role") == "user"]
        question = self._text(users[-1])
        if "04/10/2026 au 10/10/2026" in question:
            return self._analysis(history)
        tables = [self._text(item) for item in history if item.get("role") == "assistant"]
        proposals = [
            (message, category)
            for table in tables
            for message, category in re.findall(r"\| (controlled-\d+) \| (PROJECT_ALPHA|FINANCE) \|", table)
        ]
        if not proposals:
            return [self._message("Périmètre précédent indisponible; préciser la sélection.")]
        last_user = max(index for index, item in enumerate(history) if item.get("role") == "user")
        if any(item.get("type") == "function_call_output" for item in history[last_user + 1:]):
            return [self._message(f"{len(proposals)} affectations en attente de confirmation; aucune modification.")]
        return [
            self._call("apply_label", {"message_id": message, "label_id": category}, index)
            for index, (message, category) in enumerate(proposals)
        ]

    def _analysis(self, history):
        outputs = {
            item["call_id"]: json.loads(item["output"][item["output"].index("{"):])
            for item in history if item.get("type") == "function_call_output"
        }
        if not outputs:
            return [
                self._call("search_mail", {
                    "date_from": "2026-10-04T00:00:00+00:00",
                    "date_to": "2026-10-10T23:59:59.999999+00:00", "limit": 50,
                }, "search"),
                self._call("list_labels", {}, "labels"),
            ]
        results = outputs["call_scope_search"]["results"]
        labels = {item["label_id"] for item in outputs["call_scope_labels"]["labels"]}
        rows = []
        for item in results:
            category = self._category(item["subject"], labels)
            rows.append(f"| {item['message_id']} | {category} |")
        return [self._message(
            "Sélection du 04/10/2026 au 10/10/2026 inclus (7 jours).\n"
            "| Mail | Catégorie existante |\n| --- | --- |\n" + "\n".join(rows)
        )]

    @staticmethod
    def _category(subject, labels):
        for marker, category in (("Project Alpha", "PROJECT_ALPHA"), ("Invoice", "FINANCE")):
            if marker in subject and category in labels:
                return category
        return "Non classé"

    @staticmethod
    def _text(item):
        content = item.get("content", [])
        if isinstance(content, str):
            return content
        return "".join(part.get("text", "") for part in content)

    @staticmethod
    def _message(text):
        return {
            "type": "message", "id": "msg_scope", "role": "assistant", "status": "completed",
            "content": [{"type": "output_text", "text": text, "annotations": []}],
        }

    @staticmethod
    def _call(name, arguments, index):
        return {
            "type": "function_call", "id": f"fc_scope_{index}", "call_id": f"call_scope_{index}",
            "name": name, "arguments": json.dumps(arguments), "status": "completed",
        }

    @staticmethod
    def _stream(response):
        events = [{
            "type": "response.created", "response": {**response, "status": "in_progress", "output": []},
        }]
        for index, item in enumerate(response["output"]):
            events.append({"type": "response.output_item.added", "output_index": index, "item": item})
            if item["type"] == "message":
                events.append({
                    "type": "response.output_text.delta", "item_id": item["id"],
                    "output_index": index, "content_index": 0, "delta": item["content"][0]["text"],
                })
            else:
                events.append({
                    "type": "response.function_call_arguments.delta", "item_id": item["id"],
                    "output_index": index, "delta": item["arguments"],
                })
            events.append({"type": "response.output_item.done", "output_index": index, "item": item})
        events.append({"type": "response.completed", "response": response})
        data = "".join(f"event: {item['type']}\ndata: {json.dumps(item)}\n\n" for item in events)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=data)
