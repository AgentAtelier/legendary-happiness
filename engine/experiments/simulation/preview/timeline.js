let timelineFrames = []
let currentFrame = 0

async function loadTimeline(){

const res = await fetch("/preview/timeline")
timelineFrames = await res.json()

buildTimeline()

}

function buildTimeline(){

const slider = document.getElementById("timelineSlider")

if(!slider) return

const length = timelineFrames.rain?.length ?? 0

slider.max = length-1
slider.value = length-1

currentFrame = length-1

updateTimelineFrame()

}

function updateTimelineFrame(){

if(!timelineFrames.rain) return

const index = document.getElementById("timelineSlider").value

const snapshot = {}

Object.keys(timelineFrames).forEach(key=>{

snapshot[key] = timelineFrames[key][index]?.value

})

document.getElementById("timelineData").textContent =
JSON.stringify(snapshot,null,2)

}

function timelineChanged(){

currentFrame = document.getElementById("timelineSlider").value

updateTimelineFrame()

}