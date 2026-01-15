import{r as i,j as e}from"./vendor-react-RhKMXzW9.js";import{B as o,t as r}from"./index-tqyCjUUg.js";import{p as F}from"./python-strategy-BRRmegCS.js";import{A as I,a as T}from"./alert-CK9xBWjU.js";import{C as g,b as y,c as j,d as L,a as N}from"./card-BJaCi6EE.js";import{C as z,b as B,a as M}from"./collapsible-CVvMrHJf.js";import{I as K}from"./input-CM6ORX-p.js";import{L as b}from"./label-CwmP25mB.js";import{A as O,I as U,aB as v,aL as C}from"./vendor-icons-Ca5eNZvr.js";import{a as Y,L as D}from"./vendor-router-DdyOoyPF.js";import"./vendor-radix-gKv__6YA.js";const S=`"""
Example OpenAlgo Strategy
This is a minimal example showing how to use the OpenAlgo Python SDK.
"""

import os
import time
from openalgo import api

# Get API key from environment variable
API_KEY = os.getenv('OPENALGO_API_KEY')

# Initialize the API client
client = api(
    api_key=API_KEY,
    host_url="http://127.0.0.1:5000"
)

def main():
    """Main strategy logic"""
    print("Strategy started")

    # Example: Get account funds
    funds = client.funds()
    print(f"Available funds: {funds}")

    # Your trading logic here
    while True:
        # Check market conditions
        # Place orders based on your strategy
        # ...

        time.sleep(60)  # Check every minute

if __name__ == "__main__":
    main()
`;function ee(){const d=Y(),m=i.useRef(null),[a,p]=i.useState(""),[n,w]=i.useState(null),[h,x]=i.useState(!1),[u,P]=i.useState(!1),[l,A]=i.useState({}),_=()=>{const s={};return a.trim()?a.length<3||a.length>50?s.name="Name must be between 3 and 50 characters":/^[a-zA-Z0-9\s\-_]+$/.test(a)||(s.name="Name can only contain letters, numbers, spaces, hyphens, and underscores"):s.name="Strategy name is required",n?n.name.endsWith(".py")||(s.file="File must be a Python file (.py)"):s.file="Please select a Python file",A(s),Object.keys(s).length===0},E=s=>{const t=s.target.files?.[0];if(t){if(!t.name.endsWith(".py")){r.error("Please select a Python file (.py)");return}const c=1024*1024;if(t.size>c){r.error("File size must be less than 1MB");return}if(w(t),!a){const f=t.name.replace(".py","").replace(/_/g," ");p(f.charAt(0).toUpperCase()+f.slice(1))}}},k=async s=>{if(s.preventDefault(),!_()){r.error("Please fix the form errors");return}try{x(!0);const t=await F.uploadStrategy(a,n);t.status==="success"?(r.success("Strategy uploaded successfully"),d(`/python/${t.data?.strategy_id}/edit`)):r.error(t.message||"Failed to upload strategy")}catch(t){console.error("Failed to upload strategy:",t);const c=t instanceof Error?t.message:"Failed to upload strategy";r.error(c)}finally{x(!1)}};return e.jsxs("div",{className:"container mx-auto py-6 max-w-2xl space-y-6",children:[e.jsx(o,{variant:"ghost",asChild:!0,children:e.jsxs(D,{to:"/python",children:[e.jsx(O,{className:"h-4 w-4 mr-2"}),"Back to Python Strategies"]})}),e.jsxs("div",{children:[e.jsx("h1",{className:"text-2xl font-bold tracking-tight",children:"Add Python Strategy"}),e.jsx("p",{className:"text-muted-foreground",children:"Upload a Python script to run as an automated trading strategy"})]}),e.jsxs(I,{children:[e.jsx(U,{className:"h-4 w-4"}),e.jsxs(T,{children:["Your Python script should use the ",e.jsx("code",{className:"bg-muted px-1 rounded",children:"openalgo"})," ","SDK. Install it with: ",e.jsx("code",{className:"bg-muted px-1 rounded",children:"pip install openalgo"})]})]}),e.jsxs(g,{children:[e.jsxs(y,{children:[e.jsxs(j,{className:"flex items-center gap-2",children:[e.jsx(v,{className:"h-5 w-5"}),"Upload Strategy"]}),e.jsx(L,{children:"Select your Python script file and give it a name"})]}),e.jsx(N,{children:e.jsxs("form",{onSubmit:k,className:"space-y-6",children:[e.jsxs("div",{className:"space-y-2",children:[e.jsx(b,{htmlFor:"name",children:"Strategy Name"}),e.jsx(K,{id:"name",placeholder:"My Trading Strategy",value:a,onChange:s=>p(s.target.value),className:l.name?"border-red-500":""}),l.name&&e.jsx("p",{className:"text-sm text-red-500",children:l.name}),e.jsx("p",{className:"text-xs text-muted-foreground",children:"A descriptive name for your strategy"})]}),e.jsxs("div",{className:"space-y-2",children:[e.jsx(b,{htmlFor:"file",children:"Python Script"}),e.jsxs("div",{className:`border-2 border-dashed rounded-lg p-6 text-center cursor-pointer hover:border-primary transition-colors ${l.file?"border-red-500":""}`,onClick:()=>m.current?.click(),children:[e.jsx("input",{ref:m,id:"file",type:"file",accept:".py",className:"hidden",onChange:E}),n?e.jsxs("div",{className:"flex items-center justify-center gap-2",children:[e.jsx(C,{className:"h-8 w-8 text-green-500"}),e.jsxs("div",{className:"text-left",children:[e.jsx("p",{className:"font-medium",children:n.name}),e.jsxs("p",{className:"text-sm text-muted-foreground",children:[(n.size/1024).toFixed(2)," KB"]})]})]}):e.jsxs("div",{children:[e.jsx(v,{className:"h-8 w-8 mx-auto text-muted-foreground mb-2"}),e.jsx("p",{className:"text-sm text-muted-foreground",children:"Click to select a Python file (.py)"}),e.jsx("p",{className:"text-xs text-muted-foreground mt-1",children:"Maximum file size: 1MB"})]})]}),l.file&&e.jsx("p",{className:"text-sm text-red-500",children:l.file})]}),e.jsxs("div",{className:"flex gap-3 pt-4",children:[e.jsx(o,{type:"button",variant:"outline",className:"flex-1",onClick:()=>d("/python"),children:"Cancel"}),e.jsx(o,{type:"submit",className:"flex-1",disabled:h,children:h?"Uploading...":"Upload Strategy"})]})]})})]}),e.jsx(z,{open:u,onOpenChange:P,children:e.jsxs(g,{children:[e.jsx(y,{children:e.jsx(B,{asChild:!0,children:e.jsxs(o,{variant:"ghost",className:"w-full justify-between p-0",children:[e.jsxs(j,{className:"text-lg flex items-center gap-2",children:[e.jsx(C,{className:"h-5 w-5"}),"Example Strategy Template"]}),e.jsx("span",{className:"text-muted-foreground",children:u?"Hide":"Show"})]})})}),e.jsx(M,{children:e.jsxs(N,{children:[e.jsx("pre",{className:"p-4 bg-muted rounded-lg overflow-x-auto text-xs font-mono",children:S}),e.jsx(o,{variant:"outline",size:"sm",className:"mt-4",onClick:()=>{navigator.clipboard.writeText(S),r.success("Copied to clipboard")},children:"Copy Template"})]})})]})})]})}export{ee as default};
