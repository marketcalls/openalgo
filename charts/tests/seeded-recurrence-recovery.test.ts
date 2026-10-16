import { describe, expect, it } from 'vitest';
import { rma, smaSeededEma } from '../src/indicators/calc';
import { ema, emaSeries } from '../src/indicators/ema';
import { MACD } from '../src/indicators/momentum';
import { ALLIGATOR, TEMA } from '../src/indicators/averages';
import { WAVETREND } from '../src/indicators/wavetrend';
import { EMA } from '../src/indicators/trend';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

// Independent small-window expectations, also checked through actual compiled
// programs in both script engines. null denotes absence, never a zero source.
const fixtures = [
  {"id":"ordinary","period":3,"values":[0,3,6,9,3],"multiply":false,
    "expected":{"ema":[null,null,3,6,4.5],"rma":[null,null,3,5,4.333333333333333]}},
  {"id":"leading-seed-hole","period":3,"values":[null,0,3,6,9,3],"multiply":false,
    "expected":{"ema":[null,null,null,3,6,4.5],"rma":[null,null,null,3,5,4.333333333333333]}},
  {"id":"interior-seed-hole","period":3,"values":[0,null,3,6,9,3],"multiply":false,
    "expected":{"ema":[null,null,null,null,6,4.5],"rma":[null,null,null,null,6,5]}},
  {"id":"repeated-seed-holes","period":3,"values":[null,0,null,3,null,6,9,12],"multiply":false,
    "expected":{"ema":[null,null,null,null,null,null,null,9],"rma":[null,null,null,null,null,null,null,9]}},
  {"id":"running-hole","period":3,"values":[0,3,6,null,9,3],"multiply":false,
    "expected":{"ema":[null,null,3,null,6,4.5],"rma":[null,null,3,null,5,4.333333333333333]}},
  {"id":"generated-infinity-after-seed","period":3,"values":[0,0,0,2,1],"multiply":true,
    "expected":{"ema":[null,null,0,null,5e+307],"rma":[null,null,0,null,3.333333333333333e+307]}},
  {"id":"generated-infinity-before-seed","period":3,"values":[2,0,0,0,1],"multiply":true,
    "expected":{"ema":[null,null,null,0,5e+307],"rma":[null,null,null,0,3.333333333333333e+307]}},
  {"id":"overflowing-seed-retry","period":2,"values":[1e+308,1e+308,1,2],"multiply":false,
    "expected":{"ema":[null,null,5e+307,1.6666666666666669e+307],"rma":[null,null,5e+307,2.5e+307]}},
  {"id":"seed-order-after-overflow","period":3,"values":[1e+308,1e+308,-1e+308,3,6],"multiply":false,
    "expected":{"ema":[null,null,null,1,3.5],"rma":[null,null,null,1,2.6666666666666665]}},
  {"id":"committed-running-overflow","period":3,"values":[0,0,0,1.7e+308,1.7e+308,null,0],"multiply":false,
    "expected":{"ema":[null,null,0,8.5e+307,1.2749999999999999e+308,null,6.374999999999999e+307],"rma":[null,null,0,5.666666666666667e+307,null,null,null]}},
  {"id":"singleton-gap","period":1,"values":[null,4,null,8,2],"multiply":false,
    "expected":{"ema":[null,4,null,8,2],"rma":[null,4,null,8,2]}},
  {"id":"rounded-zero-seed","period":2,"values":[0,5e-324,5e-324],"multiply":false,
    "expected":{"ema":[null,0,5e-324],"rma":[null,0,0]}}
];
const consumers = [
  {"id":"macd","values":[0,3,6,9,12,15,null,18,12,21,15,24],
    "expected":{"macd":[null,null,1.5,1.5,1.5,1.5,null,1.5,0,1.25,0.04166666666666785,1.3263888888888893],"signal":[null,null,null,1.5,1.5,1.5,null,1.5,0.5,1,0.36111111111111194,1.0046296296296302],"histogram":[null,null,null,0,0,0,null,0,-0.5,0.25,-0.3194444444444441,0.3217592592592591]}},
  {"id":"tema","values":[0,3,6,9,12,15,null,18,12,21,15,24],
    "expected":{"tema":[null,null,null,null,null,null,null,null,null,20,16.09375,22.859375]}},
  {"id":"alligator","values":[0,3,6,9,12,15,null,18,12,21,15,24],
    "expected":{"jaw":[null,null,3,5,7.333333333333333,9.888888888888888,null,12.59259259259259,12.395061728395058,15.263374485596705,15.175582990397805,18.117055326931872],"teeth":[null,null,3,5,7.333333333333333,9.888888888888888,null,12.59259259259259,12.395061728395058,15.263374485596705,15.175582990397805,18.117055326931872],"lips":[null,null,3,5,7.333333333333333,9.888888888888888,null,12.59259259259259,12.395061728395058,15.263374485596705,15.175582990397805,18.117055326931872]}},
  {"id":"wavetrend","values":[100,100.25,100.5,100.75,101,101.25,101.5,101.75,102,102.25,102.5,102.75,103,103.25,103.5,null,104,104.25,104.5,104.75,105,105.25,105.5,105.75],
    "expected":{"wt1":[null,null,null,null,null,null,null,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,null,72,69.86666666666667,67.18315789473685,65.4950799220273,64.80429433002797,64.75322336418594,65.01162983600206,65.3659522605756],"wt2":[null,null,null,null,null,null,null,null,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,66.66666666666667,null,null,70.93333333333334,68.52491228070176,66.33911890838208,65.14968712602763,64.77875884710696,64.88242660009399,65.18879104828883],"mom":[null,null,null,null,null,null,null,null,0,0,0,0,0,0,0,null,null,-1.0666666666666629,-1.3417543859649044,-0.844038986354775,-0.34539279599965766,-0.025535482921014818,0.12920323590806504,0.1771612122867623],"buy":[null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,64.88242660009399,null],"sell":[null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null,null]}}
];
const numbers = (values: readonly (number | null)[]) => values.map(value => value ?? NaN);
const barsOf = (values: readonly (number | null)[]): Bar[] => values.map((value, i) => ({
  time: 1700000000 + i * 60, open: value ?? NaN, high: value ?? NaN,
  low: value ?? NaN, close: value ?? NaN, volume: 1,
}));
const kernels = [{ name: 'ema', run: smaSeededEma }, { name: 'rma', run: rma }] as const;

describe('default seeded recurrence recovery', () => {
  for (const fixture of fixtures) it(fixture.id, () => {
    const values = numbers(fixture.values).map(value => fixture.multiply ? value * 1e308 : value);
    for (const { name, run } of kernels) {
      expect(run(values, fixture.period), name).toEqual(numbers(fixture.expected[name]));
      expect(run(values, fixture.period, undefined), name).toEqual(numbers(fixture.expected[name]));
    }
  });

  it.each(kernels)('$name is causal and recomputes after transient forming data', ({ name, run }) => {
    for (const fixture of fixtures) {
      const values = numbers(fixture.values).map(value => fixture.multiply ? value * 1e308 : value);
      for (let end = 0; end <= values.length; end++) {
        expect(run(values.slice(0, end), fixture.period)).toEqual(numbers(fixture.expected[name].slice(0, end)));
      }
      run([...values.slice(0, -1), 17], fixture.period);
      expect(run(values, fixture.period)).toEqual(numbers(fixture.expected[name]));
    }
  });

  it.each(kernels)('$name preserves unsupported scalar paths', ({ run }) => {
    for (const period of [0, -1, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      expect(run([1,2,3,4], period)).toEqual([NaN,NaN,NaN,NaN]);
    }
    expect(run([1,2,3,4], NaN)).toEqual(Object.assign([NaN,NaN,NaN,NaN], { NaN }));
    expect(run([1,2,3,4], 1.5)).toEqual(Object.assign([NaN,NaN,NaN,NaN], {
      '0.5': 2, '1.5': NaN, '2.5': NaN, '3.5': NaN,
    }));
  });

  it('retains the distinct explicit hold and restart policies', () => {
    const values = [0,3,6,NaN,9,3,12];
    expect(smaSeededEma(values,3,{missing:'skip'})).toEqual([NaN,NaN,3,3,6,4.5,8.25]);
    expect(rma(values,3,{missing:'skip'})).toEqual([NaN,NaN,3,3,5,13/3,6.888888888888888]);
    for (const run of [smaSeededEma,rma]) for (const options of [{}, {missing:'propagate' as const}]) {
      expect(run(values,3,options)).toEqual([NaN,NaN,3,NaN,NaN,NaN,8]);
    }
  });

  it('keeps first-value base EMA and its bar helper unchanged', () => {
    expect(ema([0,3,6],3)).toEqual([0,1.5,3.75]);
    expect(emaSeries(barsOf([0,3,6]),3).map(bar=>bar.close)).toEqual([0,1.5,3.75]);
  });

  it.each(kernels)('$name normalizes a negative underflowed seed to positive zero', ({name,run}) => {
    const result=run([-Number.MIN_VALUE,0,Number.MIN_VALUE],2);
    expect(Object.is(result[1],0)).toBe(true);
    expect(result[2]).toBe(name==='ema'?Number.MIN_VALUE:0);
  });

  it.each(kernels)('$name keeps ordinary finite bits and linear source access', ({ name, run }) => {
    const values=Array.from({length:20000},(_,i)=>100+(i%113)/7), period=500;
    let reads=0;
    const watched=new Proxy(values,{get(target,key,receiver){
      if(typeof key==='string' && /^\d+$/.test(key)) reads++;
      return Reflect.get(target,key,receiver);
    }});
    const actual=run(watched,period);
    expect(reads).toBeLessThanOrEqual(values.length+period+2);
    const expected=new Array<number>(values.length).fill(NaN);
    let previous=values.slice(0,period).reduce((sum,value)=>sum+value,0)/period;
    expected[period-1]=previous;
    const weight=2/(period+1);
    for(let i=period;i<values.length;i++) {
      previous=name==='ema'?values[i]*weight+previous*(1-weight):(previous*(period-1)+values[i])/period;
      expected[i]=previous;
    }
    expect(actual).toEqual(expected);
  });
});

describe('composed seeded study recovery', () => {
  it('resumes MACD and its signal from independent saved recurrence states', () => {
    const item=consumers.find(c=>c.id==='macd')!;
    const actual=MACD.calc(barsOf(item.values),{...indicatorDefaults(MACD),source:'close',fastPeriod:2,slowPeriod:3,signalPeriod:2},{});
    expect(actual).toEqual(item.expected);
  });

  it('preserves additive TEMA warmup then resumes every level after the gap', () => {
    const item=consumers.find(c=>c.id==='tema')!;
    expect(TEMA.calc(barsOf(item.values),{...indicatorDefaults(TEMA),length:3},{})).toEqual(item.expected);
  });

  it('resumes Alligator Wilder averages without moving their source timestamps', () => {
    const item=consumers.find(c=>c.id==='alligator')!;
    expect(ALLIGATOR.calc(barsOf(item.values),{...indicatorDefaults(ALLIGATOR),jawLength:3,teethLength:3,lipsLength:3,jawOffset:0,teethOffset:0,lipsOffset:0},{})).toEqual(item.expected);
  });

  it('recovers WaveTrend without a cross-gap event, retaining a later genuine event', () => {
    const item=consumers.find(c=>c.id==='wavetrend')!;
    const actual=WAVETREND.calc(barsOf(item.values),{...indicatorDefaults(WAVETREND),source:'close',n1:3,n2:4,sigLen:2,filterZone:false},{});
    for(const key of ['wt1','wt2','mom','buy','sell'] as const) expect(actual[key],key).toEqual(item.expected[key]);
    expect(actual.buy.slice(15,18)).toEqual([null,null,null]);
    expect(actual.sell.slice(15,18)).toEqual([null,null,null]);
    expect(actual.buy[22]).toBe(64.88242660009399);
  });

  it('changes only the EMA descriptor default source policy, preserving resolved propagation', () => {
    const source={kind:'indicator',instanceId:'producer',plotKey:'value'} as const;
    const column=[1,3,null,7,9,11];
    const bars=barsOf(column);
    expect(EMA.calc(bars,{source:'close',length:2},{}).ma).toEqual([null,2,null,16/3,70/9,268/27]);
    expect(EMA.calc(bars,{source,length:2},{},{barState:{isNew:false,isConfirmed:true,isRealtime:false,lastIndex:5},timezone:'Etc/UTC',now:()=>0,resolveSource:()=>column}).ma)
      .toEqual([null,2,null,null,8,10]);
  });
});
