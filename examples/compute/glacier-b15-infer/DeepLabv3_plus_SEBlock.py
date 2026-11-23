import torch.nn as nn
import math
import torch
import torch.nn.functional as F

# device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

class SEBlock(nn.Module):
    """
    Squeeze-and-Excitation (SE) Block for channel attention.
    压缩全局信息，然后激发通道权重。reduction控制压缩比率。
    用于直接加权输入波段，强调特定通道。
    """
    def __init__(self, channels, reduction=16, bias_init_channels=None):
        super(SEBlock, self).__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)  # 全局平均池化
        self.fc1 = nn.Linear(channels, channels // reduction, bias=True)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(channels // reduction, channels, bias=True)
        self.sigmoid = nn.Sigmoid()
        
        # 初始化偏置，引导关注特定通道（如果提供bias_init_channels列表）
        if bias_init_channels:
            with torch.no_grad():
                for idx in bias_init_channels:
                    if idx < channels:  # 防止索引越界（深层通道数大）
                        self.fc2.bias[idx] += 0.1

    def forward(self, x):
        b, c, _, _ = x.size()
        y = self.avg_pool(x).view(b, c)  # Squeeze: [b, c, 1, 1] -> [b, c]
        y = self.fc1(y)
        y = self.relu(y)
        y = self.fc2(y)
        y = self.sigmoid(y).view(b, c, 1, 1)  # Excitation: 通道权重
        return x * y  # 乘以原特征，实现动态加权

class ASPP(nn.Module):
    """
    空洞卷积，卷积核，步长，补全有变化，输入尺寸不变，通道数自己定义
    """
    def __init__(self, input_, output_, dilation):
        super(ASPP, self).__init__()
        if dilation == 1:
            k_size = 1
            padding = 0
        else:
            k_size = 3
            padding = dilation
        self.cond_aspp = nn.Conv2d(
            input_,
            output_,
            kernel_size=k_size,
            padding=padding,
            dilation=dilation)
        self.bn = nn.BatchNorm2d(output_)
        self.relu = nn.ReLU()
        self._init_weight

    def forward(self, x):
        x = self.cond_aspp(x)
        x = self.bn(x)
        x = self.relu(x)
        return x

    def _init_weight(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

class Bottleneck(nn.Module):
    """
    残差模块，最终通道数=参数中的output_*4，和输入无关
    同时，采用了paddin，数据尺寸按照os=8设定步长[1,2,1,1]
    最终缩小2倍
    保持通道数一致，
    可以相加。
    修改：嵌入SEBlock在残差块末尾（bn3后），动态加权输出通道。
    """
    expansion = 4

    def __init__(self, input_, output_, stride=1, dilation=1, downsample=None):
        super(Bottleneck, self).__init__()
        self.conv1 = nn.Conv2d(input_, output_, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm2d(output_)
        self.conv2 = nn.Conv2d(
            output_,
            output_,
            kernel_size=3,
            stride=stride,
            padding=dilation,
            dilation=dilation,
            bias=False)
        self.bn2 = nn.BatchNorm2d(output_)
        self.conv3 = nn.Conv2d(output_, output_*4, kernel_size=1, bias=False)
        self.bn3 = nn.BatchNorm2d(output_*4)
        self.relu = nn.ReLU(inplace=True)
        
        # 新增：嵌入SEBlock，应用于残差块输出通道 (output_*4)
        # 注意：深层通道已融合，不再针对原始index 8/9加bias（可选移除bias_init）
        self.se = SEBlock(channels=output_*4, reduction=16)  # bias_init_channels=[8,9] 可选，如果想引导特定融合通道
        
        self.downsample = downsample
        self.stride = stride
        self.dilation = dilation

    def forward(self, x):
        initdata = x
        out = self.conv1(x)  # 卷积核大小1，改变维度
        out = self.bn1(out)
        out = self.relu(out)
        out = self.conv2(out)  # 空洞按照参数设定
        out = self.bn2(out)
        out = self.relu(out)
        out = self.conv3(out)
        out = self.bn3(out)
        
        # 新增：应用嵌入的SEBlock，动态加权残差输出
        out = self.se(out)

        if self.downsample is not None:
            initdata = self.downsample(x)
        out += initdata
        out = self.relu(out)
        return out

class ResNet(nn.Module):
    """
    残差深度神经网络，主要改进加上空洞卷积。尺寸会缩小，通道数自己定义。
    修改：使用带嵌入SEBlock的Bottleneck构建层。
    """

    def __init__(self, input_, block, layers, os=16, pretrained=False):
        super(ResNet, self).__init__()
        self.inplanes = 64
        if os == 16:
            strides = [1, 2, 2, 1]
            dilations = [1, 1, 1, 2]
            blocks = [1, 2, 4]
        elif os == 8:
            strides = [1, 2, 1, 1]
            dilations = [1, 1, 2, 2]
            blocks = [1, 2, 1]
        else:
            raise NotImplementedError
        self.conv1 = nn.Conv2d(
            input_,
            64,
            kernel_size=7,
            stride=2,
            padding=3,
            bias=False)
        self.bn1 = nn.BatchNorm2d(64)
        self.relu = nn.ReLU(inplace=True)
        self.maxpool = nn.MaxPool2d(kernel_size=3, stride=2, padding=1)

        # 尺寸不变，通道数变为给定值的4倍
        # 使用带SE的Bottleneck构建各层
        self.layer1 = self._make_layer(
            block, 64, layers[0], stride=strides[0], dilation=dilations[0])  # 第二个参数为通道数
        self.layer2 = self._make_layer(
            block, 128, layers[1], stride=strides[1], dilation=dilations[1])
        self.layer3 = self._make_layer(
            block, 256, layers[2], stride=strides[2], dilation=dilations[2])
        self.layer4 = self._make_MG_unit(
            block, 512, blocks=blocks, stride=strides[3], dilation=dilations[3])
        self._init_weight()

    def _make_layer(self, block, planes, blocks, stride=1, dilation=1):  # blocks层数
        """
        保证残差模块相加的时候通道数一致
        """
        downsample = None
        if stride != 1 or self.inplanes != planes*block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes*block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes*block.expansion),
            )
        layers = []
        layers.append(block(self.inplanes, planes,
                      stride, dilation, downsample))
        self.inplanes = planes*block.expansion
        for i in range(1, blocks):
            layers.append(block(self.inplanes, planes))

        return nn.Sequential(*layers)

    def _make_MG_unit(self, block, planes, blocks, stride=1, dilation=1):
        """
        保证残差模块相加的时候通道数一致
        """
        downsample = None
        if stride != 1 or self.inplanes != planes*block.expansion:
            downsample = nn.Sequential(
                nn.Conv2d(self.inplanes, planes*block.expansion,
                          kernel_size=1, stride=stride, bias=False),
                nn.BatchNorm2d(planes*block.expansion,)
            )
        layers = []
        layers.append(block(self.inplanes, planes, stride,
                      blocks[0]*dilation, downsample))
        self.inplanes = planes*block.expansion
        for i in range(1, len(blocks)):
            layers.append(block(self.inplanes, planes))

        return nn.Sequential(*layers)

    def forward(self, input):
        x = self.conv1(input)  # 步长为2，输出通道为64，因此尺寸减少一半128
        x = self.bn1(x)
        x = self.relu(x)
        x = self.maxpool(x)  # 尺寸减少一半64，通道数不变
        x = self.layer1(x)  # 经过残差模块，通道数变为输出通道数的四倍4*64
        low_level_feat = x  # (1,256,64,64)
        x = self.layer2(x)  # (1,512,32,32)
        x = self.layer3(x)  # (1,1024,32,32)
        x = self.layer4(x)  # (1,2048,32,32)
        return x, low_level_feat

    def _init_weight(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                n = m.kernel_size[0] * m.kernel_size[1] * m.out_channels
                m.weight.data.normal_(0, math.sqrt(2. / n))
            elif isinstance(m, nn.BatchNorm2d):
                m.weight.data.fill_(1)
                m.bias.data.zero_()

class DeepLabv3_plus_SEBlock(nn.Module):  # 修改类名为 DeepLabv3_plus_SEBlock
    """
    数据进来之后，经过残差网络，生成一个深度的特征，和一个初始化的特征，深度特征进入到ASPP中，
    经过融合上采样和初始化的特征融合，然后再经过卷积上采样，得到最终结果，主要是用到空洞卷积，
    同时，长链操作还是存在的。
    修改：ResNet使用嵌入SEBlock的Bottleneck；原se_input可选保留（这里注释掉，焦点在嵌入）。
    """

    def __init__(self, num_classes=3, band_num=15, os=8):  # 更新为3类，15波段
        super(DeepLabv3_plus_SEBlock, self).__init__()  # 修改为 DeepLabv3_plus_SEBlock
        # 原输入SEBlock：可选保留作为额外预处理；这里注释，焦点在ResNet内部嵌入
        # self.se_input = SEBlock(band_num, bias_init_channels=[8, 9])  # 直接应用于输入的15通道
        
        # 修改：使用带嵌入SE的Bottleneck初始化ResNet
        self.resnet_feature = ResNet(band_num, Bottleneck, [3, 4, 6, 3], os)
        if os == 16:
            dilation = [1, 6, 12, 18]
        if os == 8:
            dilation = [1, 12, 24, 36]
        else:
            raise NotImplementedError
        self.aspp1 = ASPP(2048, 256, dilation=dilation[0])
        self.aspp2 = ASPP(2048, 256, dilation=dilation[1])
        self.aspp3 = ASPP(2048, 256, dilation=dilation[2])
        self.aspp4 = ASPP(2048, 256, dilation=dilation[3])
        self.relu = nn.ReLU()

        self.global_avg_pool = nn.Sequential(
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Conv2d(2048, 256, 1, stride=1, bias=False)
        )

        self.conv1 = nn.Conv2d(1280, 256, 1, bias=False)
        self.bn1 = nn.BatchNorm2d(256)

        self.conv2 = nn.Conv2d(256, 48, 1, bias=False)
        self.bn2 = nn.BatchNorm2d(48)

        self.last_conv = nn.Sequential(nn.Conv2d(304, 256, kernel_size=3, stride=1, padding=1, bias=False),
                                       nn.BatchNorm2d(256),
                                       nn.ReLU(),
                                       nn.Conv2d(256, 256, kernel_size=3,
                                                 stride=1, padding=1, bias=False),
                                       nn.BatchNorm2d(256),
                                       nn.ReLU(),
                                       nn.Conv2d(256, num_classes, kernel_size=1, stride=1))

    def forward(self, input):
        # 原输入SE：可选，如果保留取消注释
        # input = self.se_input(input)
        
        x, low_level_features = self.resnet_feature(
            input)  # (1,2048,32,32) (1,256,64,64)
        x1 = self.aspp1(x)  # (1,256,32,32)
        x2 = self.aspp2(x)
        x3 = self.aspp3(x)
        x4 = self.aspp4(x)  # (1,256,32,32)
        x5 = self.global_avg_pool(x)  # (1,256,1,1)
        x5 = F.interpolate(x5, size=x4.size()[
                           2:], mode='bilinear', align_corners=True)  # (1,256,32,32)

        x = torch.cat((x1, x2, x3, x4, x5), dim=1)  # (1,1280,32,32) #上采样
        x = self.conv1(x)  # (1,256,32,32)
        x = self.bn1(x)
        x = self.relu(x)
        x = F.interpolate(x, size=(int(math.ceil(input.size()[-2]/4)),
                                   int(math.ceil(input.size()[-1]/4))), mode='bilinear', align_corners=True)
        # (1,256,64,64)

        low_level_features = self.conv2(low_level_features)  # (1,48,64,64)
        low_level_features = self.bn2(low_level_features)
        low_level_features = self.relu(low_level_features)

        # 拼接低层次的特征，然后再通过插值获取原图大小的结果
        x = torch.cat((x, low_level_features), dim=1)
        x = self.last_conv(x)  # (1,3,64,64)  # 输出3通道

        x = F.interpolate(x, size=input.size()[
                          2:], mode='bilinear', align_corners=True)  # (1,3,256,256)
        
        # 更新为softmax（互斥多类：背景/洁净/表碛）
        return F.softmax(x, dim=1)
