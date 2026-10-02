'use client';
import { useState } from 'react';

type Point={name:string;x:number;y:number};
type Result={initial_route:string[];optimized_route:string[];initial_distance:number;optimized_distance:number;improvement:number;improvement_rate:number};
const initial:Point[]=[{name:'A',x:0,y:0},{name:'B',x:2,y:6},{name:'C',x:5,y:3},{name:'D',x:6,y:7},{name:'E',x:8,y:2},{name:'F',x:1,y:4},{name:'G',x:7,y:5},{name:'H',x:3,y:1}];
export default function Home(){
 const [points,setPoints]=useState<Point[]>(initial); const [result,setResult]=useState<Result|null>(null); const [loading,setLoading]=useState(false); const [error,setError]=useState('');
 const update=(i:number,k:keyof Point,v:string)=>setPoints(p=>p.map((x,n)=>n===i?{...x,[k]:k==='name'?v:Number(v)}:x));
 const optimize=async()=>{setLoading(true);setError('');try{const r=await fetch(`${process.env.NEXT_PUBLIC_API_URL??'http://localhost:8000'}/optimize`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({points})});if(!r.ok)throw new Error(await r.text());setResult(await r.json());}catch(e){setError(e instanceof Error?e.message:'Optimization failed');}finally{setLoading(false)}};
 return <main><h1>ヒューリスティック経路最適化</h1><p>貪欲法で初期解を生成し、2-opt局所探索で巡回距離を改善します。</p><section><h2>地点</h2>{points.map((p,i)=><div className="row" key={i}><input value={p.name} onChange={e=>update(i,'name',e.target.value)} aria-label={`name-${i}`}/><input type="number" value={p.x} onChange={e=>update(i,'x',e.target.value)} aria-label={`x-${i}`}/><input type="number" value={p.y} onChange={e=>update(i,'y',e.target.value)} aria-label={`y-${i}`}/><button onClick={()=>setPoints(x=>x.filter((_,n)=>n!==i))} disabled={points.length<=3}>削除</button></div>)}<button onClick={()=>setPoints(p=>[...p,{name:String.fromCharCode(65+p.length),x:0,y:0}])}>地点追加</button> <button className="primary" onClick={optimize} disabled={loading}>{loading?'探索中…':'最適化実行'}</button>{error&&<p className="error">{error}</p>}</section>{result&&<section><h2>結果</h2><div className="cards"><article><b>初期距離</b><span>{result.initial_distance}</span></article><article><b>最適化後</b><span>{result.optimized_distance}</span></article><article><b>改善率</b><span>{result.improvement_rate}%</span></article></div><h3>初期経路</h3><p>{result.initial_route.join(' → ')}</p><h3>最適化経路</h3><p>{result.optimized_route.join(' → ')}</p></section>}</main>
}
