# Запись факта
1. Прежде чем писать, вызови ask по смыслу факта. Такой факт уже есть - дополни его источником (add_source), нового не заводи.
2. Один факт - одно минимальное утверждение. `claim`: 20-200 символов, одна строка, без «а также» и перечислений. Тело и summary пиши на английском, русские термины клади в aliases.
3. `summary` - тот же факт без контекста: читается отдельно от хаба и книги, без «в этой главе», «как выше».
4. `kind`: definition, mechanism, constraint, tradeoff, number, convention, api, pitfall, comparison, step, snippet. Код допустим только в kind: snippet, в разделе Example. Нормативное «следует делать» - convention.
5. `valid_for` обязателен для number, api и pitfall: условие вида `rust>=1.75` или метка `kernel:io_uring`. Для kind: number укажи value, unit, conditions, measured_at.
6. `confidence`: sourced - только если цитата проверена сервисом при ingest; иначе inferred. Нужна проверка человеком - open. Обе стороны противоречия не правь сам: свяжи их через contradicts.
7. Привяжи факт к хабу: relations.about на подходящий topic или tech. Подходящего нет - предложи хаб draft в том же предложении. Домен выбирай из schema/domains.yaml; нового домена агент не создаёт.
8. Связи с другими фактами (supports, refines, applies_with, precedes) - только если уверен; вес связи не выше базового.
9. Не уверен в факте - не записывай его как истину: propose_fact с confidence: inferred либо question. Публикация и повышение остаются за человеком.
