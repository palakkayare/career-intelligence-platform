# Re-identification Risk Assessment

**Salary insights — Career Intelligence Platform**
Required by blueprint Feature 14. Prepared 10 September 2026.

---

## Why this exists

People submit their salary on the understanding that no published figure can
be traced back to them. This assessment asks whether that holds, and it found
that it did not.

Three defects were found and fixed. The fix for the third is not the one this
assessment first proposed - the first two attempts failed against a realistic
distribution. The rest of the document is the reasoning.

---

## What is published

`GET /api/v1/career-intel/salary-insights/` accepts seven filters:

| Filter | Values |
|---|---|
| `role_title` | free text |
| `target_role_id` | 7 seeded roles |
| `location_city` | free text |
| `company_size_bucket` | 5 |
| `experience_years_bucket` | 4 |
| `industry_id` | seeded industries |
| `effective_year` | 2-year window by default |

Any combination is allowed. That is the attack surface: a caller narrows the
population until it is small, then reads what comes back.

The guard is K-anonymity — nothing is returned below `SALARY_K_ANONYMITY`
(default 5) submissions, checked again after outlier trimming.

---

## Finding 1 — the endpoint published individual salaries

**Severity: high. Fixed.**

The response included `min` and `max`.

Neither is an aggregate in any protective sense. The minimum of a set is one
person's exact salary. So is the maximum. Publishing them alongside a K
threshold is a contradiction: the threshold exists to stop individual figures
being readable, and these were individual figures.

The differencing attack this enables takes two requests:

```
A: role=Backend Developer, city=Indore              → 6 rows, max = ₹42,00,000
B: role=Backend Developer, city=Indore, exp=10+     → 5 rows, max = ₹28,00,000
```

The person in A but not B earns ₹42,00,000. Their experience bucket, role and
city are all known from the query. In a city with few senior backend
engineers, that is an identification.

**Fix:** `min` and `max` are no longer returned.

---

## Finding 2 — at K=5, the percentiles were also individuals

**Severity: high. Fixed.**

This one is less obvious and matters more.

`calculate_percentile` interpolates by rank: `index = (p/100) × (n-1)`. When
that index is a whole number, the result is not a blend — it is exactly one
person's value.

At n=5:

| Figure | Index | Result |
|---|---|---|
| p25 | 0.25 × 4 = **1.0** | `values[1]` exactly |
| median | 0.50 × 4 = **2.0** | `values[2]` exactly |
| p75 | 0.75 × 4 = **3.0** | `values[3]` exactly |

So at the K threshold itself, every published percentile was one submitter's
exact salary. Removing min and max would not have helped: the median was doing
the same thing.

This recurs at every n where `(p/100) × (n-1)` is an integer — n=5, 9, 13 for
the quartiles. It is not an edge case at the boundary; it is a periodic
property of rank interpolation on small samples.

**Fix:** published figures are rounded to a ₹50,000 band
(`round_for_publication`). A banded figure describes a range, not a person.

₹50,000 is roughly 3% of a mid-level Indian salary — wide enough to create
ambiguity, narrow enough that the number still guides a negotiation. The
trade-off is tested: `test_the_rounded_median_still_describes_the_data`
asserts the published median stays within half a band of the true one.

---

## Finding 3 — banding alone could not fix sparse distributions

**Severity: medium. Fixed, but not the way this assessment first proposed.**

The first fix for Finding 2 was a flat ₹50,000 rounding band. Testing it
against a realistic senior distribution showed it did not work:

```
₹30L  ₹45L  ₹55L  ₹70L  ₹80L      median = ₹55L exactly
```

The nearest neighbour is ₹10L away. No band narrow enough to leave the number
useful comes anywhere near creating ambiguity — making that median ambiguous
would need ±₹10L, which destroys it.

Making the band proportional to the median (5%, so ₹2.75L here) did not fix it
either. The band is the wrong tool: it moves the published number a little,
and the neighbours are nowhere near.

**The actual cause** is that rank interpolation returns a member whenever the
index is whole. Rounding was addressing the symptom.

**Fix:** `publication_percentile` takes the midpoint of the value and its
neighbour when the index is whole. The published median for the distribution
above is ₹62.5L — between two people, belonging to neither.

The band is retained, because it does something different: it stops a
published figure being an exact number that can be matched against outside
knowledge. The two defences work on different attacks.

`calculate_percentile` is unchanged and still used for the server-side
comparison, where the output is a category rather than a number.

**Worth recording:** the first two proposed fixes were both wrong, and only
testing against a realistic distribution showed it. An assessment that had
stopped at "round the figures" would have shipped a defence that fails
precisely where the population is thinnest and the salary most identifying.

## Finding 4 — free-text filters are unbounded

**Severity: medium. Not fixed.**

`role_title` and `location_city` are free text matched with `iexact`. A caller
can probe arbitrary strings — "Staff Engineer, Payments", "Indore" — and each
distinct value is a slice of the population.

The K threshold still applies to every slice, so nothing is returned below 5.
The residual risk is inference by absence: if `role=Chief Architect,
city=Bhopal` returns nothing and the attacker knows one person holds that
title there, they have learned that person did not submit. That is a weak
disclosure but it is a disclosure.

**Mitigation available:** restrict to `target_role_id` and a curated city
list. It costs coverage — someone whose title is not in the taxonomy cannot
see insights at all — so it is a product decision rather than a clear win.

---

## Finding 5 — the author link

**Severity: low as implemented. Resolved by wording, not by code.**

`SalarySubmission.user` is a foreign key to the submitter. It is needed for
deduplication and is never exposed through any aggregation endpoint.

Under DPDP this makes the collection **pseudonymous, not anonymous**.

This assessment originally proposed replacing the foreign key with a keyed
hash of the user id. That was wrong, and the reasoning is worth keeping:

The hash has to be deterministic or deduplication breaks — "one submission per
user per role per year" needs to recognise a returning submitter. Deterministic
means anyone with the pepper can recompute it. Data export needs the same
capability, because a person asking what is held about them has to be answered.

So the hash is pseudonymisation in disguise, treated identically under DPDP,
and arguably worse than the foreign key because the schema looks anonymous to
anyone reading it.

**The constraint underneath: deduplication requires linkability.** "One
submission per person" and "truly anonymous" cannot both hold, and
deduplication is not optional — without it one person can move a published
median on their own.

**Resolution: the link stays; the product copy changes.** Accurate wording is
recorded in `DATA_PROTECTION.md` gap 4.

---

## What holds up

The parts that were already correct:

- **K checked after trimming.** Five submissions where two are junk leaves
  three; checking only before would make the guarantee cosmetic.
  (`test_trimming_can_push_a_sample_back_below_the_threshold`)
- **Flagged submissions excluded from every aggregate.**
- **One submission per user per role per year**, so one person cannot move a
  median alone.
- **IP stored as a keyed HMAC**, never in the clear, with the pepper separate
  from `SECRET_KEY`.
- **Per-device rate limiting**, three submissions per IP per 24 hours.
- **Two-year window**, which also limits how long any single submission stays
  in a published figure.

---

## Is K=5 the right number?

Not derived from this dataset — it was chosen as a common default.

The reasoning that supports it: at 5, with min and max removed and the
remaining figures banded, no single figure resolves to one person on a
normally-distributed sample.

The reasoning against: 5 is thin for the intersections that matter most.
"Product Manager, Indore, 10+ years" plausibly has fewer than five holders in
the whole city, so the threshold blocks the query — which is the right
outcome. But "Backend Developer, Bangalore, 10+ years" will clear 5 easily
while still being a small, well-connected community where people know each
other's approximate salaries and could place a published figure.

**K=5 is defensible with Findings 1 and 2 fixed. It should be revisited once
there is real submission data**, using the distribution of actual
role/city/experience combinations rather than an assumption.

---

## Before launch

| # | Action | Blocking |
|---|---|---|
| 1 | Apply the wording from `DATA_PROTECTION.md` gap 4 to user-facing copy | Yes |
| 2 | Decide on Finding 4 — free-text filters | No |
| 3 | Revisit K against real data once ~500 submissions exist | No |

Findings 1, 2 and 3 are fixed in code. Finding 5 is resolved by wording.
Finding 4 is a coverage-versus-privacy trade-off that only matters once there
is enough data for the absence of a result to mean something.

---

## How to verify

```bash
pytest apps/career_intel/test_salary.py -v
```

The defences described here are covered by:

| Defence | Test |
|---|---|
| min/max not published | `test_the_exact_minimum_and_maximum_are_not_published` |
| Figures banded | `test_published_figures_are_rounded_to_a_band` |
| No figure is anybody's salary | `test_no_published_figure_is_anybodys_salary` |
| Whole indices blended | `test_a_whole_index_never_returns_a_member` |
| Sparse groups protected | `test_a_widely_spread_group_still_hides_its_members` |
| Differencing blocked | `test_a_differencing_attack_does_not_isolate_one_person` |
| K after trimming | `test_trimming_can_push_a_sample_back_below_the_threshold` |
| IP hashing | `test_a_different_pepper_gives_a_different_hash` |
| Usefulness preserved | `test_the_rounded_median_still_describes_the_data` |

---

*Three defects found and fixed. One wording change outstanding.*
*This is an engineering assessment, not a legal opinion.*
