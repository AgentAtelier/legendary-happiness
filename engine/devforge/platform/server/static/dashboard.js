let traces_cache = []
let selected_trace = null

// ------------------------------------------------------------
// Refresh Loop
// ------------------------------------------------------------

async function refresh() {

    try {

        const status = await fetch("/dashboard/api/status").then(r => r.json())
        const traces = await fetch("/dashboard/api/traces").then(r => r.json())

        document.getElementById("status").innerText =
            JSON.stringify(status, null, 2)

        traces_cache = traces

        renderTraceList()

    } catch (err) {

        console.error("Dashboard refresh error:", err)

    }

}


// ------------------------------------------------------------
// Render Trace List
// ------------------------------------------------------------

function renderTraceList() {

    const container = document.getElementById("trace_list")

    container.innerHTML = ""

    traces_cache.forEach(trace => {

        const div = document.createElement("div")

        div.className = "trace_item"

        let status_icon = "✓"

        if (trace.status === "error") {
            status_icon = "✗"
        }

        div.innerText =
            status_icon + " " +
            trace.trace_id + " | " +
            trace.prompt.slice(0, 40)

        div.onclick = () => showTrace(trace)

        container.appendChild(div)

    })

}


// ------------------------------------------------------------
// Show Selected Trace
// ------------------------------------------------------------

function showTrace(trace) {

    selected_trace = trace

    document.getElementById("trace_details").innerText =
        JSON.stringify(trace, null, 2)

}


// ------------------------------------------------------------
// Copy Run Log
// ------------------------------------------------------------

function copyRunLog() {

    const text =
        document.getElementById("trace_details").innerText

    if (!text) {
        alert("Nothing to copy")
        return
    }

    navigator.clipboard.writeText(text)

    alert("Run log copied")

}


// ------------------------------------------------------------
// Send Prompt
// ------------------------------------------------------------

async function sendPrompt() {

    const prompt = document.getElementById("prompt_input").value

    if (!prompt || prompt.trim() === "") {
        alert("Enter a prompt first")
        return
    }

    const payload = {
        prompt: prompt,
        scene_tree: {}
    }

    try {

        await fetch("/generate", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify(payload)
        })

        alert("Prompt sent")

    } catch (err) {

        console.error(err)

        alert("Failed to send prompt")

    }

}


// ------------------------------------------------------------
// Start Dashboard
// ------------------------------------------------------------

refresh()

setInterval(refresh, 2000)