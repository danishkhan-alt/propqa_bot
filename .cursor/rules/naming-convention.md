---
name: clear-naming
description: Enforces intuitive, intent-revealing names for every identifier a coding agent creates — variables, functions, classes, files, constants, types, and config keys. Use this automatically whenever writing new code, reviewing a diff, or renaming something, not just when the user explicitly asks about naming. If a name needs a comment to explain what it holds or does, that is a signal to stop and apply this skill before moving on.
---

# Clear Naming

Bad names are a silent tax: every person (or agent) who touches the code later has to re-derive intent that a good name would have given away for free. This skill makes naming a deliberate step, not an afterthought typed in the half-second before moving to the next line.

## The core rule

**A name should answer "what is this / what does this do / why does it exist" without forcing the reader to open the implementation.** If someone has to read the function body to know what to expect from its name, the name has failed.

Three things a good name does simultaneously:
1. **States intent** — the purpose, not the mechanism (`retryQueue`, not `list2`)
2. **Matches its scope of truth** — a name promises something; the code must keep that promise (a function called `getUser` should not also delete a session as a side effect)
3. **Costs nothing to read aloud** — if you'd stumble explaining it verbally to a teammate, rename it

## Before committing to any name, run this checklist

- [ ] Does the name say *what it is/does*, not *how it's implemented*? (`activeUsers`, not `filteredList`)
- [ ] Could I delete the type/kind from the name without losing information? If yes, the name is doing the type's job instead of its own (`accountsArray` → `accounts`)
- [ ] Is it pronounceable and searchable? (`genymdhms` fails both; `generationTimestamp` passes)
- [ ] Does it use one word per concept, consistently, across the whole codebase? (pick `fetch`, `get`, or `retrieve` — not all three for the same kind of operation)
- [ ] For a boolean: does it read as a yes/no question? (`isReady`, `hasPermission`, `canRetry` — not `status` or `flag`)
- [ ] For a function: does the name match everything the function actually does, including side effects? If it does two things, either the name needs "and" (a smell) or the function needs splitting
- [ ] Would a new team member guess the correct usage from the name alone, with no docstring?
- [ ] Have I avoided disinformation — names that imply something false (`userList` that's actually a `Map`, `accounts` that's actually a single account)?

If a name fails more than one of these, don't ship it — this skill exists specifically to catch that before it happens.

---

## Category-by-category guide

### 1. Variables — name the thing, not its container or history

| Bad | Good | Why |
|---|---|---|
| `d` | `elapsedDays` | Unit and meaning both missing from `d` |
| `data` | `parsedInvoices` | "data" is true of every variable ever; says nothing |
| `temp` | `unsavedDraft` | "temp" describes lifetime, not purpose |
| `flag` | `isDiscountEligible` | Say what the flag *means*, not that it's a flag |
| `list1`, `list2` | `pendingOrders`, `shippedOrders` | Numbers are a cop-out for "I didn't decide what distinguishes these" |
| `usrLst` | `users` | Vowel-dropping saves no real time and slows every future reader |
| `obj` | `invoice` | Never name a variable after its type when a domain word exists |

### 2. Booleans — phrase as a question with an unambiguous answer

| Bad | Good |
|---|---|
| `status` | `isActive` |
| `check` | `hasExpired` |
| `enable` | `isEnabled` / `shouldRetry` |
| `visible` (ambiguous: state or command?) | `isVisible` |
| `notFound` | `wasFound` (avoid negatives — `if (!notFound)` is a double-negative trap) |

Avoid negated booleans entirely where possible (`isDisabled` reads worse than `isEnabled` at every call site: `if (!isDisabled)` vs `if (isEnabled)`).

### 3. Functions / methods — name the effect, and only the effect

A function name is a contract. Everything inside the function should be explainable by its name alone.

| Bad | Good | Why |
|---|---|---|
| `handleData()` | `normalizePhoneNumbers()` | "handle" and "process" mean nothing — they describe that code runs, not what it does |
| `doStuff()` | `archiveExpiredSessions()` | Same problem, more extreme |
| `getUserAndLogAccess()` | split into `getUser()` + `logAccess()` | An "and" in a function name means it's doing two jobs — split it, don't just document it |
| `checkValid()` | `isValid()` (returns bool) or `validate()` (throws/returns errors) | "check" is ambiguous about what happens on failure — pick a verb that implies the return contract |
| `updateUser()` that also sends an email | `updateUserAndNotify()`, or split | The name must include every observable side effect, or the side effect should be moved out |
| `save()` on a class with only one thing to save | fine as-is | Context (the class name) can carry meaning — don't over-qualify when the surrounding scope already disambiguates |

Verb conventions worth picking once and enforcing everywhere in a codebase:
- `get` → cheap, synchronous, no side effects
- `fetch` → I/O involved (network, disk), may fail or be slow
- `create` → allocates a new thing
- `ensure` → idempotent "make this true if it isn't already"
- `is` / `has` / `can` / `should` → booleans only

### 4. Classes / types — nouns that name a single responsibility

| Bad | Good | Why |
|---|---|---|
| `Manager`, `Helper`, `Util`, `Processor` (as a suffix on everything) | `InvoiceReconciler`, `RetryScheduler` | Generic suffixes are where unrelated logic goes to accumulate — the name should describe the one responsibility, forcing you to notice when a class has grown a second one |
| `Data` | `CustomerProfile` | Every class holds "data" — say whose and what kind |
| `AbstractBaseManagerImpl` | `PaymentGateway` (interface) / `StripeGateway` (impl) | Encoding the pattern (Abstract/Impl/Base) into the name is noise once you can see the type hierarchy in the code itself |
| `IUserService` (Hungarian-style prefix) | `UserService` | Let the language's type system communicate "interface" — don't also spell it out in the name |

### 5. Constants & config keys — say what the value constrains, with units

| Bad | Good |
|---|---|
| `MAX` | `MAX_RETRY_ATTEMPTS` |
| `TIMEOUT` | `REQUEST_TIMEOUT_MS` (unit in the name prevents a whole class of bugs) |
| `FLAG_1` | `FEATURE_NEW_CHECKOUT_ENABLED` |
| `LIMIT` | `MAX_UPLOAD_SIZE_BYTES` |

### 6. Collections — plural nouns that say what's inside, and consider the shape

| Bad | Good | Why |
|---|---|---|
| `userList` | `users` (if it's a list) | The variable's type is visible from its declaration; don't duplicate it unless multiple structures holding the same entity coexist in scope |
| `userMap` | `usersById` | For a Map/Dict, naming the *key* removes the single biggest source of confusion at every call site |
| `data` | `ordersByRegion` | Say both what's inside and how it's organized |

### 7. Files & modules — name the single reason the file exists

| Bad | Good |
|---|---|
| `utils.js` / `helpers.py` (a dumping ground) | `dateFormatting.js`, `csvParsing.py` — split by responsibility |
| `index.js` with unrelated exports | one cohesive concern per file; `index.js` only re-exports |
| `new_user_v2_final.py` | `user_onboarding.py` — versioning belongs in git history, not filenames |

### 8. Short-lived / tiny-scope variables — the one place brevity is fine

Single-letter names are acceptable **only** when the scope is a few lines and the convention is universal:
- `i`, `j` in a tight numeric `for` loop
- `x`, `y` for coordinates
- `_` for an intentionally-unused value

Outside those narrow cases, scope size does not excuse a bad name — a `map()` callback with real logic still deserves `order => order.total` over `o => o.t`.

---

## Common smells to flag on sight

| Smell | Example | Fix |
|---|---|---|
| **Noise words** | `userInfo`, `userData`, `userObject` all in one file | Drop the noise word; if you need three, differentiate by what's actually different (`userProfile`, `userSession`, `userAuditLog`) |
| **Type-in-name** | `accountArray`, `nameString`, `countInt` | Delete the type suffix; the declaration already gives the type |
| **Disinformation** | a variable called `accounts` (plural) holding one account; a `List` called `...Queue` when it has no FIFO guarantee | Rename to match actual behavior, not aspirational behavior |
| **Mental mapping** | single-letter names reused across a long function, forcing the reader to hold a lookup table in their head | Give each one a real name once the scope exceeds a few lines |
| **Inconsistent vocabulary** | `fetchUser`, `getOrder`, `retrieveInvoice` for the same kind of operation across a codebase | Standardize on one verb per operation type, everywhere |
| **False parallelism** | `sendEmail()` and `SMSNotifier.send()` for equivalent operations | Keep naming *and* structure parallel for things that are conceptually parallel |
| **Over-abbreviation** | `calcTtlAmtUsd()` | Spell it out: `calculateTotalAmountUsd()` — editors autocomplete; brains don't |
| **Encoding scope/type in the name (Hungarian notation)** | `strName`, `m_count`, `g_config` | Rely on the type system and scoping rules instead |

---

## Worked example

**Before:**
```python
def proc(d, f=True):
    r = []
    for x in d:
        if x.get('s') == 1 and (f or x.get('t') > 0):
            r.append(x)
    return r
```

**After:**
```python
def select_active_orders(orders, include_untouched_orders=True):
    active_orders = []
    for order in orders:
        is_active = order.get('status') == OrderStatus.ACTIVE
        has_activity = order.get('touch_count') > 0
        if is_active and (include_untouched_orders or has_activity):
            active_orders.append(order)
    return active_orders
```

Nothing about the logic changed — only the names. The second version is readable without the caller ever opening the function body, and a reviewer can spot a logic bug (e.g. wrong operator) far faster because the variable names describe what's *supposed* to happen.

---

## How to apply this skill in practice

1. **While writing new code**: before typing a name, silently finish the sentence "this holds/does ___". Use that phrase, trimmed, as the name.
2. **While reviewing a diff**: flag any identifier that needed a comment next to it to be understood, or that duplicates a name already used for something else in the file.
3. **When renaming**: change the name everywhere it's referenced (declaration, call sites, tests, docs, log messages) in the same change — a rename that leaves the old word in half the file is worse than not renaming at all.
4. **When two names are both defensible**: prefer the one that reads correctly at the *call site*, since names are written once but read at every usage (`isEmpty(list)` reads better than `empty(list)`).