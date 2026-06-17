async function loadParameters(){

const res = await fetch("/preview/parameters")
const data = await res.json()

const container = document.getElementById("parameters")

container.innerHTML=""

Object.entries(data).forEach(([system,params])=>{

const section=document.createElement("div")
section.innerHTML=`<h4>${system}</h4>`

params.forEach(p=>{

const wrapper=document.createElement("div")
wrapper.className="param"

const label=document.createElement("label")
label.textContent=p.name

const slider=document.createElement("input")

slider.type="range"
slider.min=p.min??0
slider.max=p.max??1
slider.step=p.step??0.01
slider.value=p.value

const value=document.createElement("div")
value.className="param-value"
value.textContent=p.value

slider.oninput=async()=>{

value.textContent=slider.value

await fetch("/preview/set_parameter",{
method:"POST",
headers:{"Content-Type":"application/json"},
body:JSON.stringify({
system:system,
parameter:p.name,
value:parseFloat(slider.value)
})
})

}

wrapper.appendChild(label)
wrapper.appendChild(slider)
wrapper.appendChild(value)

section.appendChild(wrapper)

})

container.appendChild(section)

})

}