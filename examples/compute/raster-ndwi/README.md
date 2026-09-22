# NDWI水体指数

输入多波段反射率影像，选择绿光和近红外波段。按 McFeeters NDWI 定义计算 `(Green − NIR) / (Green + NIR)`，应用影像自带 scale/offset；无效值及零分母输出 NoData。

输出单波段 Float32 GeoTIFF，保留输入坐标系、分辨率和范围。波段编号从1开始，应按传感器实际排列选择。该指数适合水体判读，阈值需结合区域、阴影和地物条件确定。
