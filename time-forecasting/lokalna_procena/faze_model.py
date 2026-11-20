"""Statička analiza lokalnog izvora i procena trajanja po fazama."""
import ast
from collections import Counter
from dataclasses import dataclass
import math
from pathlib import Path

OPS = ('loop','arithmetic','mod','index','mapping','allocate','sort','call')
DATASETS = {'make_classification','make_regression','make_blobs'}
MODELS = {'BaggingClassifier','BaggingRegressor','RandomForestClassifier','RandomForestRegressor',
          'ExtraTreesClassifier','ExtraTreesRegressor','IsolationForest','DecisionTreeClassifier',
          'DecisionTreeRegressor','ExtraTreeClassifier','ExtraTreeRegressor','LogisticRegression',
          'LinearRegression','Ridge','StandardScaler'}


@dataclass
class Array:
    n: int
    d: int = 1


@dataclass
class Learner:
    name: str
    params: dict


def numeric(value, default):
    return value if type(value) in (int,float) and math.isfinite(value) else default


def size(value):
    return value.n if isinstance(value,Array) else len(value) if isinstance(value,(tuple,list,range)) else None


def draw(value, full, auto):
    if value=='auto':
        return min(auto,full)
    if isinstance(value,float):
        return max(1,int(full*value))
    return max(1,min(full,int(numeric(value,full))))


class Analysis:
    def __init__(self, model, path=None):
        self.model=model
        self.root=Path(path).resolve().parent if path else None
        self.ops=Counter()
        self.phases=Counter()
        self.issues=set()
        self.imports=set()
        self.fits=[]
        self.modules={}
        self.depth=0

    def parse(self, text, path):
        return self.block(ast.parse(text).body, {'__file__':path}, 1)

    def block(self, statements, env, mult):
        for item in statements:
            if isinstance(item, (ast.Import,ast.ImportFrom)):
                for alias in item.names:
                    module=item.module if isinstance(item,ast.ImportFrom) else alias.name
                    module=module or ''
                    self.imports.add(module.split('.')[0])
                    bound=alias.asname or alias.name
                    env[bound]=alias.name
                    if self.root and module.isidentifier() and module not in ('os','sys','math','pathlib','random'):
                        file=(self.root/(module+'.py')).resolve()
                        if file.parent==self.root and file.is_file() and file.stat().st_size<256000:
                            if module not in self.modules:
                                scope={'__file__':file}
                                self.modules[module]=scope
                                self.block(ast.parse(file.read_text()).body,scope,1)
                            scope=self.modules[module]
                            env[bound]=scope.get(alias.name) if isinstance(item,ast.ImportFrom) else scope
            elif isinstance(item,ast.FunctionDef):
                env[item.name]=(item,env)
            elif isinstance(item,ast.ClassDef):
                env[item.name]={m.name:(m,env) for m in item.body if isinstance(m,ast.FunctionDef)}
            elif isinstance(item,ast.Return):
                return self.expr(item.value,env,mult)
            elif isinstance(item,(ast.Assign,ast.AnnAssign)):
                val=self.expr(item.value,env,mult)
                for target in (item.targets if isinstance(item,ast.Assign) else [item.target]):
                    self.bind(target,val,env,mult)
            elif isinstance(item,ast.For):
                seq=self.expr(item.iter,env,mult)
                count=size(seq)
                if count is None:
                    count=1
                    self.issues.add('Nepoznata dužina petlje')
                self.ops['loop']+=mult*count
                sub=env.copy()
                self.bind(item.target,None,sub,mult)
                self.block(item.body,sub,mult*count)
            elif isinstance(item,ast.If):
                if '__main__' in ast.unparse(item.test):
                    self.block(item.body,env,mult)
                else:
                    self.issues.add('Približna učestalost uslovne grane')
                    self.block(item.body,env.copy(),mult*.5)
                    self.block(item.orelse,env.copy(),mult*.5)
            elif isinstance(item,ast.AugAssign):
                self.ops['arithmetic']+=mult
                self.expr(item.target,env,mult)
                self.expr(item.value,env,mult)
            elif isinstance(item,ast.Expr):
                self.expr(item.value,env,mult)
            elif isinstance(item,(ast.While,ast.Try,ast.With)):
                self.issues.add('Nepotpuna analiza: '+type(item).__name__)

    def bind(self,target,val,env,mult):
        if isinstance(target,ast.Name):
            env[target.id]=val
        elif isinstance(target,(ast.Tuple,ast.List)):
            for i,node in enumerate(target.elts):
                self.bind(node,val[i] if isinstance(val,(list,tuple)) and i<len(val) else None,env,mult)
        elif isinstance(target,ast.Subscript):
            self.expr(target,env,mult)

    def expr(self,node,env,mult):
        ev=lambda x:self.expr(x,env,mult)
        if isinstance(node,ast.Constant):
            return node.value
        if isinstance(node,ast.Name):
            return env.get(node.id)
        if isinstance(node,ast.Dict):
            return {}
        if isinstance(node,ast.Tuple):
            return tuple(ev(e) for e in node.elts)
        if isinstance(node,ast.List):
            self.ops['allocate']+=len(node.elts)*mult
            return Array(len(node.elts))
        if isinstance(node,ast.BinOp):
            a,b=ev(node.left),ev(node.right)
            self.ops['mod' if isinstance(node.op,ast.Mod) else 'arithmetic']+=mult
            if isinstance(a,Array) and isinstance(node.op,ast.Mult):
                n=max(0,int(numeric(b,1)))*a.n
                self.ops['allocate']+=n*mult
                return Array(n)
            if type(a) in (float,int) and type(b) in (float,int):
                try:
                    f={ast.Add:lambda:a+b,ast.Sub:lambda:a-b,ast.Mult:lambda:a*b,
                       ast.Div:lambda:a/b,ast.FloorDiv:lambda:a//b,ast.Mod:lambda:a%b}.get(type(node.op))
                    if f:
                        v=f()
                        return v if abs(v)<1e18 else None
                except ArithmeticError:
                    pass
        if isinstance(node,ast.Subscript):
            a=ev(node.value)
            self.ops['mapping' if isinstance(a,dict) else 'index']+=mult
            if isinstance(a,Array) and isinstance(node.slice,ast.Tuple):
                col=node.slice.elts[-1]
                return Array(a.n,a.d-1 if isinstance(col,ast.Slice) else 1)
            i=ev(node.slice)
            if isinstance(a,tuple) and type(i) is int and -len(a)<=i<len(a):
                return a[i]
        if isinstance(node,ast.Attribute):
            a=ev(node.value)
            if isinstance(a,Array) and node.attr=='shape':
                return (a.n,a.d)
            if isinstance(a,dict):
                return a.get(node.attr)
        if isinstance(node,(ast.ListComp,ast.GeneratorExp,ast.DictComp,ast.SetComp)):
            count=1
            for g in node.generators:
                length=size(self.expr(g.iter,env,mult*count))
                if length is None:
                    self.issues.add('Nepoznata dužina komprehenzije')
                count*=length if length is not None else 1
            self.ops['loop']+=mult*count
            self.expr(getattr(node,'elt',getattr(node,'value',None)),env,mult*count)
            return Array(count)
        if isinstance(node,ast.Call):
            return self.call(node,env,mult)
        return None

    def call(self,node,env,mult):
        attr=isinstance(node.func,ast.Attribute)
        name=node.func.attr if attr else getattr(node.func,'id','')
        obj=self.expr(node.func.value,env,mult) if attr else None
        func=obj.get(name) if isinstance(obj,dict) else env.get(name)
        if isinstance(func,str):
            name=func
        args=[self.expr(a,env,mult) for a in node.args]
        kw={k.arg:self.expr(k.value,env,mult) for k in node.keywords}
        first=args[0] if args else None
        self.ops['call']+=mult
        if isinstance(func,tuple) and len(func)==2 and isinstance(func[0],ast.FunctionDef):
            if self.depth>=12:
                self.issues.add('Dubina ili rekurzija lokalnog poziva')
                return
            definition,scope=func
            params=definition.args.args
            defaults=definition.args.defaults
            local=scope.copy()
            for p,v in zip(params[len(params)-len(defaults):],defaults):
                local[p.arg]=self.expr(v,scope,mult)
            values=([obj]+args) if attr and params and params[0].arg=='self' else args
            local.update({p.arg:v for p,v in zip(params,values)})
            local.update(kw)
            self.depth+=1
            result=self.block(definition.body,local,mult)
            self.depth-=1
            return result
        if isinstance(func,dict):
            return func
        if name=='range':
            if args and all(type(a) is int and abs(a)<1e15 for a in args):
                try: return range(*args)
                except (TypeError,ValueError): pass
            return None
        if name=='len': return size(first)
        if name in ('list','tuple'): return Array(size(first) or 0)
        if name in ('dict','Counter'): return {}
        if name=='get' and isinstance(obj,dict): self.ops['mapping']+=mult
        if name in ('sort','sorted'):
            n=size(obj if attr else first) or 1
            self.ops['sort']+=mult*n*math.log2(max(2,n))
            return Array(n)
        if name=='Path': return first
        if name=='with_name' and isinstance(obj,Path) and isinstance(first,str) and Path(first).name==first:
            return obj.with_name(first)
        if name in ('loadtxt','genfromtxt'):
            path=first if isinstance(first,Path) else self.root/first if self.root and isinstance(first,str) else None
            if self.root and path and path.resolve().parent==self.root and path.suffix=='.csv' and path.is_file() and path.stat().st_size<=16_000_000:
                # Samo redovi/kolone numeričkog CSV-a; ulazni kod se ne pokreće.
                with path.open('rb') as stream:
                    line=stream.readline()
                    count=int(bool(line))+sum(1 for _ in stream)
                self.phases['data']+=path.stat().st_size*self.model.get('csv_byte',0)*mult
                return Array(count,line.count(b',')+1)
            self.issues.add('Nepoznate dimenzije fajla')
        if name in DATASETS:
            n=int(numeric(kw.get('n_samples',first),100))
            d=int(numeric(kw.get('n_features'),20))
            self.phases['data']+=mult*n*d*self.model.get('data',0)
            return Array(n,d),Array(n)
        if name=='train_test_split' and isinstance(first,Array):
            frac=kw.get('test_size',.25)
            test=int(math.ceil(first.n*frac)) if isinstance(frac,float) else int(numeric(frac,first.n*.25))
            return tuple(v for a in args if isinstance(a,Array) for v in (Array(a.n-test,a.d),Array(test,a.d)))
        if name=='make_pipeline':
            return Learner('pipeline',{'steps':args})
        if name in MODELS or name[:1].isupper() and not attr:
            return Learner(name,kw)
        if name in ('fit','predict','transform','fit_transform','score','decision_function','fit_predict'):
            steps=obj.params['steps'] if isinstance(obj,Learner) and obj.name=='pipeline' else [obj]
            for model in steps:
                self.charge(model,name,first,mult)
            return obj if name=='fit' else first
        if name not in {'print','sum','abs','max','min','get','append','float','int','enumerate','zip','round','tolist'}:
            self.issues.add('Nerazrešen poziv: '+name)
        return None

    def charge(self,obj,action,array,mult):
        n,d=(array.n,array.d) if isinstance(array,Array) else (1000,20)
        if not isinstance(array,Array):
            self.issues.add('Nepoznat oblik ulaza za '+action)
        name=obj.name if isinstance(obj,Learner) else '?'
        kw=obj.params if isinstance(obj,Learner) else {}
        rates=self.model
        if name=='StandardScaler':
            self.phases['preprocess']+=mult*n*d*rates.get('scale',0)
            return
        if action in ('predict','predict_proba','transform','score','decision_function'):
            self.phases['predict']+=mult*n*numeric(kw.get('n_estimators'),100 if name.startswith(('Bagging','ExtraTrees','Isolation','RandomForest')) else 1)*rates.get('predict_row',0)
            return
        bag=name.startswith('Bagging')
        isolation=name=='IsolationForest'
        forest=isolation or bag or name.startswith(('ExtraTrees','RandomForest'))
        k=numeric(kw.get('n_estimators'),100 if forest else 1)
        samples=draw(kw.get('max_samples','auto' if isolation else n),n,256)
        default_features='sqrt' if name in ('RandomForestClassifier','ExtraTreesClassifier') else 1.0
        mf=kw.get('max_features',default_features)
        member_cols=draw(mf,d,d) if bag or isolation else d
        cols=max(1,int(math.sqrt(d))) if mf=='sqrt' else max(1,int(math.log2(max(2,d)))) if mf=='log2' else draw(mf,d,d)
        base=kw.get('estimator')
        if bag and isinstance(base,Learner):
            base_name=base.name
        elif isolation or name.startswith('ExtraTrees'): base_name='ExtraTree'
        elif bag or name.startswith('RandomForest'): base_name='DecisionTree'
        else: base_name=name
        if 'ExtraTree' in base_name or 'DecisionTree' in base_name:
            kind='extra' if 'ExtraTree' in base_name else 'tree'
            if isolation: cols=1
            if bag and isinstance(base,Learner):
                rule=base.params.get('max_features',member_cols)
                if rule=='sqrt':
                    cols=max(1,int(math.sqrt(member_cols)))
                elif rule=='log2':
                    cols=max(1,int(math.log2(max(2,member_cols))))
                else:
                    cols=draw(rule,member_cols,member_cols)
            depth=numeric((base.params if isinstance(base,Learner) else kw).get('max_depth'),math.log2(max(samples,2)))
            units=k*samples*cols*min(depth,math.log2(max(samples,2)))
        else:
            kind='linear'
            units=k*samples*cols
            if base_name not in ('LinearRegression','LogisticRegression','Ridge'):
                self.issues.add('Nepoznat trošak fit: '+base_name)
        self.phases['fit']+=mult*rates.get(kind,0)*units
        self.fits.append(dict(model=name,base=base_name,train_rows=n,samples_per_member=samples,
                              features_per_member=member_cols,features_per_split_or_fit=cols,members=k))


def predict(model, source, path=None):
    analyzer=Analysis(model,path)
    analyzer.parse(source,Path(path).resolve() if path else None)
    startup=model['startup']
    if 'sklearn' in analyzer.imports: startup+=model['imports']
    elif 'numpy' in analyzer.imports: startup+=model['numpy_import']
    analyzer.phases['startup_import']=startup
    analyzer.phases['python']=sum(analyzer.ops[key]*rate for key,rate in model['ops'].items())
    issues=sorted(analyzer.issues)
    return dict(seconds=sum(analyzer.phases.values()),mode='model',phases_s=dict(analyzer.phases),
                work=dict(analyzer.ops),fits=analyzer.fits,unresolved=issues,
                historical_unknown=model.get('unknown_history',{}).get(
                    'sklearn' if 'sklearn' in analyzer.imports else 'Python') if issues else None)
