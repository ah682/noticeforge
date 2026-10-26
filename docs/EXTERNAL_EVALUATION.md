# Independent notice review trial protocol

This protocol is ready for a component-engineer trial; none has been completed
yet. Existing scores use the eight synthetic development cases and OCR variants.

1. Recruit component engineers who did not build the tool or author the cases.
   Obtain consent and document permission for each notice, BOM and publication.
   Public availability alone does not establish permission for training or sharing.
2. Freeze source SHA, environment, parser/model configuration and corpus hashes.
   Have an independent reader follow the README without coaching. Record setup
   failures, elapsed time and any help needed.
3. Use unfamiliar permitted supplier notices or independently authored synthetic
   notices. Freeze gold part/date/exception relationships before parser changes;
   preserve ambiguous, unreadable, unsupported and missing-page cases. Have a
   separate knowledgeable annotator adjudicate disagreements where practical.
4. Compare the engineer's normal review/BOM workflow against NoticeForge on
   matched tasks; vary task order to reduce learning effects. Record participant
   count, case count, allocation, assistance and any exclusions in advance.
5. Measure exact part/date relationships, false assertions, missed deadlines,
   retained uncertainty, reviewer corrections and task completion time. Report
   raw per-case errors and time as well as totals. XML validity is a separate
   measure from extraction correctness and downstream receiver interoperability.
6. Publish consented anonymized results, configurations, hashes, commands and
   failures. Separate initial results from improvements and fresh holdouts.
   Small convenience samples support case studies, not general supplier accuracy
   or reliable productivity claims. Never publish a time-saving estimate without
   completed paired tasks and their denominators.

Optional model error analysis must distinguish wrong identifiers, wrong date
associations, missing/invalid evidence spans and unsupported assertions. Diagnose
these failures before choosing another training intervention. Retain the frozen
negative comparison (seven profiles: 0/19 evidence-valid relationships); do not
retune it against the same holdout. Use separate development data and a
new holdout for a future model experiment.

Suggested record: independence/consent, source SHA/runtime/OS, corpus permission
and hashes, frozen annotations, task/order, baseline method, assistance, raw
predictions, corrections, missed deadlines, timings and publication permission.
