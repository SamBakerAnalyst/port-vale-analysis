# How to update the live hub (simple guide)

Your team bookmark stays the same forever: **http://178.128.161.215**

After you change code on your Mac, do **two things**:

---

## Every time you make updates

### Step A — On your Mac (2 minutes)

1. Double-click **`Push to GitHub.command`** in Finder  
   (or run the commands it uses)

2. Wait until it says **"Pushed to GitHub OK"**

### Step B — On the server (2 minutes)

1. Open **DigitalOcean** → your droplet → **Web Console**
2. Paste **one line**:

```bash
bash /opt/port-vale-analysis/deploy/update-live.sh
```

3. Wait until it says **"Live site updated"**

4. Open your bookmark → check the tool you changed

---

## First-time setup (do once)

See the chat for Step 1, Step 2, Step 3 — only needed today.

---

## How to tell you have the latest version

Open **Pre-Match Report** → look at the toolbar badge:

| Badge | Meaning |
|-------|---------|
| `4625423f` (8 letters/numbers) | New version |
| `v138` | Old version — run Step B again |

---

## If something goes wrong

- **Mac push failed?** — GitHub may ask you to sign in in the browser. Do that once.
- **Server update failed?** — Copy the error message and send it in chat.
- **Team still sees old page?** — Hard refresh: **Cmd + Shift + R** (Mac) or **Ctrl + Shift + R** (Windows).
