function renderGraph(id,data,label){

const x=data.map(d=>d.time)
const y=data.map(d=>d.value)

Plotly.newPlot(id,[{
x:x,
y:y,
mode:"lines",
line:{width:2}
}],{
margin:{t:20},
paper_bgcolor:"#1a1d27",
plot_bgcolor:"#1a1d27",
font:{color:"#e1e4ed"},
title:label
})

}

async function updateGraphs(){

const res = await fetch("/preview/timeline")
const data = await res.json()

if(data.rain) renderGraph("rainGraph",data.rain,"Rain")
if(data.wind) renderGraph("windGraph",data.wind,"Wind")
if(data.temperature) renderGraph("tempGraph",data.temperature,"Temperature")

}