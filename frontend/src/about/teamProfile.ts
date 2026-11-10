import portrait0 from "@card-assets/team/shen-zhanfeng.png.webp";
import portrait1 from "@card-assets/team/wang-haoyu.jpeg.webp";
import portrait2 from "@card-assets/team/ma-yubo.jpeg.webp";
import portrait3 from "@card-assets/team/zhang-yihan.png.webp";
import portrait4 from "@card-assets/team/gong-xintao.jpeg.webp";
import portrait5 from "@card-assets/team/cheng-wenyan.png.webp";
import portrait6 from "@card-assets/team/huang-siqi.jpeg.webp";
import portrait7 from "@card-assets/team/li-maolin.jpeg.webp";
import portrait8 from "@card-assets/team/han-yang.jpeg.webp";
import portrait9 from "@card-assets/team/sun-shuhui.jpeg.webp";
import portrait10 from "@card-assets/team/gao-danning.jpeg.webp";

export type TeamMember = {
  id: string;
  name: string;
  englishName: string;
  email: string;
  focus: string;
  focusEn: string;
  portrait: string;
  publications: { title: string; url?: string }[];
};

export const teamMembers: TeamMember[] = [
  {
    id: "shen-zhanfeng",
    name: "沈占锋",
    englishName: "Shen Zhanfeng",
    email: "shenzf@radi.ac.cn",
    focus: "高分辨率遥感影像信息提取与计算",
    focusEn:
      "High-resolution remote-sensing image information extraction and computation",
    publications: [
      {
        title:
          "Fire risk level prediction of timber heritage buildings based on entropy and XGBoost, 2023, 通讯作者",
      },
      {
        title:
          "Crop classification methods and influencing factors of reusing historical samples based on 2D-CNN, International Journal of Remote Sensing, 2023, 通讯作者",
      },
      {
        title:
          "复杂场景下小农经营区地块级苹果园模块化制图方法框架, 地球信息科学学报, 2023, 通讯作者",
      },
      {
        title:
          "Parcel-Level Mapping of Horticultural Crop Orchards in Complex Mountain Areas Using VHR and Time-Series Images, Remote Sensing, 2022, 通讯作者",
      },
      {
        title:
          "Parcel-level mapping of horticultural crops in mountain areas using irregular time series and VHR images, taking Qixia, China as an example, Remote Sensing, 2022, 第 2 作者",
      },
      {
        title:
          "Parcel-level mapping of apple orchard in smallholder agriculture areas based on featurelevel fusion of VHR image and time-series images, International Journal of Remote Sensing, 2022, 通讯作者",
      },
      {
        title:
          "基于D-Linknet的2014年云南鲁甸Ms6.5级地震建筑物损毁与重建评估, 地震研究, 2022, 通讯作者",
      },
      {
        title:
          "Road Extraction in Mountainous Regions from High-Resolution Images Based on DSDNet and Terrain Optimization, REMOTE SENSING, 2021, 通讯作者",
      },
      {
        title:
          "Optimizing region-merging image segmentation by applying multiple merging criterions, Remote Sensing, 2021, 第 2 作者",
      },
      {
        title:
          "Geo-Parcel-Based Change Detection Using Optical and SAR Images in Cloudy and Rainy Areas, IEEE JOURNAL OF SELECTED TOPICS IN APPLIED EARTH OBSERVATIONS AND REMOTE SENSING, 2021, 通讯作者",
      },
    ],
    portrait: portrait0,
  },
  {
    id: "wang-haoyu",
    name: "王浩宇",
    englishName: "Wang Haoyu",
    email: "wanghaoyu@aircas.ac.cn",
    focus: "时空智能信息提取及高性能计算",
    focusEn:
      "Spatiotemporal information extraction and high-performance computing",
    publications: [
      {
        title:
          "全局区域相异度阈值构建稀疏尺度集模型, 中国图象图形学报, 2020, 25(09):1848-1858.",
      },
      {
        title:
          "Improvement of Region-Merging Image Segmentation Accuracy Using Multiple Merging Criteria, Remote Sensing, 2021, doi: 10.3390/rs13142782.",
        url: "https://doi.org/10.3390/rs13142782",
      },
      {
        title:
          "Parcel-level mapping of apple orchard in smallholder agriculture areas based on feature-level fusion of VHR image and time-series images, International Journal of Remote Sensing, 2022, 43(17):6195-6220.",
      },
      {
        title:
          "Individual Populus euphratica Tree Detection in Sparse Desert Forests Based on Constrained 2-D Bin Packing, IEEE Transactions on Geoscience and Remote Sensing, 2024, 62:1-19.",
      },
      {
        title:
          "Improving semantic segmentation accuracy in thin cloud interference scenarios by mixing simulated cloud-covered samples, International Journal of Applied Earth Observation and Geoinformation, 2024, 133:104087.",
      },
      {
        title:
          "The Effect of a Parcel-Aggregated Cropping Structure Mapping Method in Irrigation-Water Estimation in Arid Regions—A Case Study of the Weigan River Basin in Xinjiang, Remote Sensing, 2024, 16(21):3941.",
      },
      {
        title:
          "The patterns of the Populus euphratica forest and cropland changes upstream of the Tarim River under the policy-driven human activities during 1960-2023, International Journal of Remote Sensing, 2025, Accepted.",
      },
    ],
    portrait: portrait1,
  },
  {
    id: "ma-yubo",
    name: "马于博",
    englishName: "Ma Yubo",
    email: "mayubo24@mails.ucas.ac.cn",
    focus: "高分辨率遥感智能解译制图",
    focusEn:
      "Intelligent interpretation and mapping of high-resolution remote-sensing imagery",
    publications: [
      {
        title:
          "马于博,张爱国,王浩宇,等.基于U-ConvHDNet模型的戈壁砾幕层提取[J].测绘通报,2025,(4):68-74.DOI:10.13474/j.cnki.11-2246.2025.0412.",
        url: "https://doi.org/10.13474/j.cnki.11-2246.2025.0412",
      },
    ],
    portrait: portrait2,
  },
  {
    id: "zhang-yihan",
    name: "张依涵",
    englishName: "Zhang Yihan",
    email: "zhangyihan242@mails.ucas.ac.cn",
    focus: "农业生态遥感",
    focusEn: "Agricultural and ecological remote sensing",
    publications: [
      {
        title:
          "张依涵,沈占锋,寇雯齐,王浩宇,张驰,马于博.基于多源遥感数据的林农间作种植结构精细分类[J].农业机械学报,2025,56(10):429-436.",
      },
      {
        title:
          "Kou, W., Shen, Z., Zhang, Y., Wang, H., Ji, P., Huang, L., ... & Ma, Y. (2024). Spatio-temporal analysis of agroforestry systems in hotan using multi-source remote sensing and deep learning. Smart Agricultural Technology, 9, 100641.",
      },
    ],
    portrait: portrait3,
  },
  {
    id: "gong-xintao",
    name: "龚鑫滔",
    englishName: "Gong Xintao",
    email: "gongxintao25@mails.ucas.ac.cn",
    focus: "高光谱地质遥感与遥感找矿",
    focusEn: "Hyperspectral geological remote sensing and mineral exploration",
    publications: [],
    portrait: portrait4,
  },
  {
    id: "cheng-wenyan",
    name: "程文妍",
    englishName: "Cheng Wenyan",
    email: "chengwenyan25@mails.ucas.ac.cn",
    focus: "地质与自然资源领域的多模态智能体技术研究",
    focusEn: "Multimodal agents for geology and natural resources",
    publications: [],
    portrait: portrait5,
  },
  {
    id: "huang-siqi",
    name: "黄思圻",
    englishName: "Huang Siqi",
    email: "huangsiqi26@mails.ucas.ac.cn",
    focus: "高光谱岩心矿物识别、智能编录和找矿预测",
    focusEn:
      "Hyperspectral core mineral identification, intelligent logging and mineral prospectivity prediction",
    publications: [],
    portrait: portrait6,
  },
  {
    id: "li-maolin",
    name: "李茂林",
    englishName: "Li Maolin",
    email: "limaolin26@mails.ucas.ac.cn",
    focus:
      "荒漠化与土地退化；生态遥感与建模；森林生态网络与碳汇；灾害环境风险计算",
    focusEn:
      "Desertification and land degradation; ecological remote sensing and modelling; forest ecological networks and carbon sinks; disaster and environmental risk computation",
    publications: [
      {
        title:
          "Maolin Li, Buyanbaatar Avirmed, Ganbold Bayanmunkhd, Yilin Liu, Yu Wang, Xinyu Yang, Yu Zhang, Qiang Yu. Assessment, driving mechanism identification and future scenario projection of desertification vulnerability in the Mongolian Plateau: an integrated study using multi-source data and machine learning[J]. Ecological Indicators, 2025, 180: 114340.DOI：https://doi.org/10.1016/j.ecolind.2025.114340第1作者。",
        url: "https://doi.org/10.1016/j.ecolind.2025.114340",
      },
      {
        title:
          "Maolin Li, Buyanbaatar Avirmed, Ganbold Bayanmunkh, Yilin Liu, Yu Wang, Xinyu Yang, Yu Zhang, Qiang Yu. Unveiling Drivers and Projecting Future Risks of Desertification Vulnerability in the Mongolian Plateau[J]. Remote Sensing, 2025, 17(14): 2389.DOI：https://doi.org/10.3390/rs17142389第1作者。",
        url: "https://doi.org/10.3390/rs17142389",
      },
      {
        title:
          "Maolin Li, Yingda Wu, Yilin Liu, Yu Zhang, Qiang Yu. Study on the Driving Factors of the Spatiotemporal Pattern in Forest Lightning Fires and 3D Fire Simulation Based on Cellular Automata[J]. Forests, 2024, 15(11): 1857.DOI：https://doi.org/10.3390/f15111857第1作者。",
        url: "https://doi.org/10.3390/f15111857",
      },
      {
        title:
          "Maolin Li, Qiang Yu, Chenglong Xu, Jikai Zhao, Yufan Zeng, Yu Wang, Yilin Liu. Research on the Carbon Sequestration Capacity of Forest Ecological Network Topological Features and Network Optimization Based on Modification Recognition in the Yellow River Basin Mining Area: A Case Study of Jincheng City[J]. Remote Sensing, 2024, 16(11): 1986.DOI：https://doi.org/10.3390/rs16111986第1作者。",
        url: "https://doi.org/10.3390/rs16111986",
      },
      {
        title:
          "Xia Yang, Buyanbaatar Avirmed, Chuangjun Xu, Yangping Wang, Huanjia Cui, Yilin Liu, Maolin Li, Bin Chi, Ji Ying Long, Qiang Yu. Greening–Function Decoupling and Land Degradation Risks in the Mongolian Plateau[J]. Land Degradation & Development, 2026, 37(11): 6600–6616.DOI：https://doi.org/10.1002/ldr.70535第7作者。",
        url: "https://doi.org/10.1002/ldr.70535",
      },
      {
        title:
          "Yu Wang, Yingda Wu, Huanjia Cui, Yilin Liu, Maolin Li, Xinyu Yang, Jikai Zhao, Qiang Yu. Extreme Climate Drivers and Their Interactions in Lightning-Ignited Fires: Insights from Machine Learning Models[J]. Forests, 2025, 16(12): 1861.DOI：https://doi.org/10.3390/f16121861第5作者。",
        url: "https://doi.org/10.3390/f16121861",
      },
      {
        title:
          "Yilin Liu, Yu Wang, Maolin Li, Qi Shi, Xinyu Yang, Bin Chi, Long Ji, Qiang Yu, Buyanbaatar Avirmed, Orgilbold Myangan, Ganbold Bayanmunkh, Dambadarjaa Naranbat. Cumulative and Lagged Drought Effects Shape Start and End of Season on the Mongolian Plateau[J]. Forests, 2025, 16(12): 1814.DOI：https://doi.org/10.3390/f16121814第3作者。",
        url: "https://doi.org/10.3390/f16121814",
      },
      {
        title:
          "Yu Zhang, Maolin Li, Qiang Yu, Buyanbaatar Avirmed, Yu Wang, Xinyu Yang. Integrating 3D radiative transfer and soil spectral models reveals soil–vegetation synergy in arid steppes[J]. Landscape Ecology, 2025, 40(12): 223.DOI：https://doi.org/10.1007/s10980-025-02249-z第2作者。",
        url: "https://doi.org/10.1007/s10980-025-02249-z",
      },
    ],
    portrait: portrait7,
  },
  {
    id: "han-yang",
    name: "韩杨",
    englishName: "Han Yang",
    email: "2025165103@stu.sdjzu.edu.cn",
    focus: "农业遥感",
    focusEn: "Agricultural remote sensing",
    publications: [],
    portrait: portrait8,
  },
  {
    id: "sun-shuhui",
    name: "孙淑慧",
    englishName: "Sun Shuhui",
    email: "2742919686@qq.com",
    focus: "农业遥感",
    focusEn: "Agricultural remote sensing",
    publications: [],
    portrait: portrait9,
  },
  {
    id: "gao-danning",
    name: "高澹宁",
    englishName: "Gao Danning",
    email: "13522057561@163.com",
    focus: "遥感大数据智能分析",
    focusEn: "Intelligent analysis of remote-sensing big data",
    publications: [],
    portrait: portrait10,
  },
];
