import pandas as pd

def run(context):
    frame=pd.read_csv(context.input_path('table'))
    group=context.parameters['group']
    value=context.parameters['value']
    if group==value:
        raise ValueError('分组字段与数值字段需要不同')
    frame[value]=pd.to_numeric(frame[value],errors='raise')
    result=frame.groupby(group,dropna=False)[value].agg(context.parameters['method']).reset_index()
    result.to_csv(context.output_path('summary.csv'),index=False,encoding='utf-8')
