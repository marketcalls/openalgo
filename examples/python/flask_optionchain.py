from flask import Flask, jsonify, request, render_template_string
from openalgo import api

app = Flask(__name__)

# Initialize API client
client = api(
    api_key="83ad96143dd5081d033abcfd20e9108daee5708fbea404121a762bed1e498dd0",
    host="http://127.0.0.1:5000"
)


# -----------------------------------------------------
# Color logic for CE/PE cells
# -----------------------------------------------------
def option_color(label):
    if not label:
        return "bg-base-200"

    lbl = label.upper()

    if lbl == "ATM":
        return "bg-yellow-400 text-black font-bold"

    if lbl.startswith("ITM"):
        return "bg-green-400/40 text-green-200"

    if lbl.startswith("OTM"):
        return "bg-red-400/40 text-red-200"

    return "bg-base-200"


# -----------------------------------------------------
# Option Chain UI — With Expiry + Strike Controls
# -----------------------------------------------------
@app.route("/")
def optionchain_ui():

    # Fetch expiry list
    expiry_data = client.expiry(
        symbol="NIFTY",
        exchange="NFO",
        instrumenttype="options"
    )
    expiry_list = expiry_data.get("data", [])

    # Selected expiry (default = first)
    selected_expiry = request.args.get(
        "expiry",
        expiry_list[0] if expiry_list else None
    )

    # Strike count selector (default = 10)
    strike_count = request.args.get("count", default=10, type=int)

    # Convert expiry "30-DEC-25" → "30DEC25" if needed
    api_expiry = selected_expiry.replace("-", "") if selected_expiry else None

    # Fetch option chain
    chain = client.optionchain(
        underlying="NIFTY",
        exchange="NSE_INDEX",
        expiry_date=api_expiry,
        strike_count=strike_count
    )

    # Template globals
    template_globals = {
        "option_color": option_color,
        "expiry_list": expiry_list,
        "selected_expiry": selected_expiry,
        "strike_count": strike_count
    }

    # -----------------------------------------------------
    # HTML Template (Supabase Green Theme + DaisyUI)
    # -----------------------------------------------------
    html = """
<!DOCTYPE html>
<html>
<head>
    <title>NIFTY Option Chain</title>

    <!-- DaisyUI + Tailwind CDN -->
    <link href="https://cdn.jsdelivr.net/npm/daisyui@4.12.10/dist/full.css" rel="stylesheet" />
    <script src="https://cdn.tailwindcss.com"></script>

    <style>
        html, body { background: #0E0F19 !important; color: #E2E8F0; }
        .supabase-green { color: #3ECF8E !important; }
        .supabase-bg { background-color: #3ECF8E !important; }
        .supabase-border { border-color: #3ECF8E !important; }
        .hover-glow:hover { box-shadow: 0 0 12px #3ECF8E; }
    </style>
</head>

<body class="p-6">

<div class="max-w-7xl mx-auto">

    <h1 class="text-3xl font-bold text-center mb-4 supabase-green">
        NIFTY Option Chain (Supabase Theme)
    </h1>

    <!-- User Controls -->
    <form method="GET" class="flex flex-wrap items-center justify-center gap-4 mb-6">

        <!-- Expiry Selector -->
        <div>
            <label class="label">
                <span class="label-text supabase-green">Expiry Date</span>
            </label>
            <select name="expiry" class="select select-bordered w-48 supabase-border hover-glow bg-[#1A1B26]">
                {% for exp in expiry_list %}
                    <option value="{{ exp }}" {% if exp == selected_expiry %} selected {% endif %}>
                        {{ exp }}
                    </option>
                {% endfor %}
            </select>
        </div>

        <!-- Strike Count -->
        <div>
            <label class="label">
                <span class="label-text supabase-green"># of Strikes</span>
            </label>
            <input name="count"
                   type="number"
                   value="{{ strike_count }}"
                   min="1"
                   max="50"
                   class="input input-bordered w-32 supabase-border bg-[#1A1B26] hover-glow">
        </div>

        <!-- Submit -->
        <div class="mt-7">
            <button class="btn supabase-bg text-black hover-glow">Load</button>
        </div>
    </form>


    {% if chain["status"] != "success" %}
        <h2 class="text-red-400 text-center text-xl">Error: {{ chain.get("message") }}</h2>

    {% else %}

    <!-- Option Chain Table -->
    <div class="overflow-x-auto rounded-xl shadow-xl border supabase-border hover-glow">
    <table class="table w-full">
        <thead>
            <tr class="bg-[#2A2B37] text-center text-white">
                <th class="supabase-green">Strike</th>
                <th colspan="2" class="text-blue-300">CALLS (CE)</th>
                <th colspan="2" class="text-pink-300">PUTS (PE)</th>
            </tr>

            <tr class="bg-[#2A2B37] text-center">
                <th class="supabase-green">Strike</th>
                <th class="text-blue-300">LTP</th>
                <th class="text-blue-300">Label</th>
                <th class="text-pink-300">LTP</th>
                <th class="text-pink-300">Label</th>
            </tr>
        </thead>

        <tbody>
        {% for item in chain["chain"] %}
            {% set ce = item.ce %}
            {% set pe = item.pe %}
            {% set ce_class = option_color(ce.label if ce else '') %}
            {% set pe_class = option_color(pe.label if pe else '') %}

            <tr class="text-center hover:bg-[#2A2B37] transition">
                <!-- Strike column -->
                <td class="font-bold {% if item.strike == chain['atm_strike'] %} bg-yellow-500 text-black {% else %} supabase-green {% endif %}">
                    {{ item.strike }}
                </td>

                <!-- CE -->
                <td class="{{ ce_class }} font-semibold">{{ ce.ltp if ce else '-' }}</td>
                <td class="{{ ce_class }}">{{ ce.label if ce else '-' }}</td>

                <!-- PE -->
                <td class="{{ pe_class }} font-semibold">{{ pe.ltp if pe else '-' }}</td>
                <td class="{{ pe_class }}">{{ pe.label if pe else '-' }}</td>

            </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>

    {% endif %}

</div>

</body>
</html>
"""

    # IMPORTANT — FIXED: pass template_globals ONLY ONCE
    return render_template_string(html, chain=chain, **template_globals)


# -----------------------------------------------------
# Run Flask
# -----------------------------------------------------
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
