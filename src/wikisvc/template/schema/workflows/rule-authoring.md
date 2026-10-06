# Добавление правила
1. Вызови get_policies(profile), rules_related по тезису и get_rule для похожих правил.
2. Сформулируй одно действие в summary (20–160 символов). Добавь русские и английские aliases.
3. Укажи category, origin, applies_to из scopes; заполни «Правило», «Обоснование», «Примеры». Примеры модели пометь для проверки.
4. Создай кандидата через предложение. Не меняй lifecycle, level, priority, owner и verified_*: решение принимает человек.
5. Ссылайся на источник; для book/article добавь короткую цитату [@src-id стр. 12 "цитата"] или гл. 2. Обязательному правилу нужны владелец и источник решения.
6. Связи refines/conflicts_with/supersedes/depends_on сохраняют контекст. Новые scopes добавляет человек через wikisvc scopes add.
7. Проверь validate и impact. Человек применяет accept с promote/deprecate либо разбирает кандидата после принятия.
