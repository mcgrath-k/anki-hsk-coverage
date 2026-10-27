# Word list sources

The per-level word lists in this folder (`*_words_level*.txt`) are the
official HSK vocabulary syllabi, one entry per line in official order,
as compiled by Rebecca J. Stone's MteH project
(https://github.com/becky82/mteh), which cross-checked them against the
published documents. Thank you, Rebecca.

- **HSK 2.0 (2012)** — Hanban, 新汉语水平考试大纲 vocabulary list
  (chinesetest.cn, `HSK-2012.xls`): 150 / 150 / 300 / 600 / 1300 / 2500
  new words per level.
- **HSK 3.0 (2021)** — 国际中文教育中文水平等级标准 (GF0025-2021), Ministry of
  Education of the PRC / Center for Language Education and Cooperation:
  500 / 772 / 973 / 1000 / 1071 / 1140 new words for levels 1–6, 5636
  for 7–9.
- **HSK 3.0 (2025)** — 新版HSK考试大纲 (Chinese Testing International,
  December 2025): 300 / 200 / 500 / 1000 / 1600 / 1800 new words for
  levels 1–6, 5600 for 7–9. Informally called "HSK 3.1" to tell it apart
  from the 2021 syllabus.

Entries keep the syllabi's notation: `爸爸|爸` (either form),
`好（不）容易` (optional character), `第（第二）` (usage example),
`喂（叹词）` (part-of-speech note), `…极了` (pattern), `称1/称2`
(homograph index). See `vocab.py` for how each is matched.

HSK is a trademark of Hanban / Chinese Testing International. This
add-on is an independent project, not affiliated with or endorsed by
them.
