# Умный ввод
1. Получи get_policies(profile). В wikiagent создай POST /chat/sessions с profile и необязательной bind к page/rule/proposal.
2. Отправь мысль через POST /chat/sessions/{id}/messages. Ответ приходит как SSE status/message/error.
3. Планировщик сохранит источник, сравнит утверждения с вики и подготовит draft. Проверь items, assumptions, questions, diff и impact.
4. Ответь на блокирующие вопросы в той же сессии. Ответ меняет существующий черновик.
5. «Применить» — запрос человека reviewer kind=human в wikisvc: POST /proposals/{pid}/accept с accept_body плана. Для must проверь владельца и источник; needs_double_confirm требует дополнительного внимания в интерфейсе.
6. Отмена закрывает черновик. Для принятого предложения чат возвращает human_action revert: агент сам его не выполняет.
