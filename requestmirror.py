# -*- coding: utf-8 -*-

import os
import json
import types
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.lighthouse.v20200324 import lighthouse_client, models
try:
    # 密钥信息从环境变量读取，需要提前在环境变量中设置 TENCENTCLOUD_SECRET_ID 和 TENCENTCLOUD_SECRET_KEY
    # 使用环境变量方式可以避免密钥硬编码在代码中，提高安全性
    # 生产环境建议使用更安全的密钥管理方案，如密钥管理系统(KMS)、容器密钥注入等
    # 请参见：https://cloud.tencent.com/document/product/1278/85305
    # 密钥可前往官网控制台 https://console.cloud.tencent.com/cam/capi 进行获取
    SecretId = os.getenv("TENCENTCLOUD_SECRET_ID")
    SecretKey = os.getenv("TENCENTCLOUD_SECRET_KEY")
    cred = credential.Credential(SecretId, SecretKey)    # 使用临时密钥示例
    # 使用临时密钥示例
    # cred = credential.Credential("SecretId", "SecretKey", "Token")
    # 实例化一个http选项，可选的，没有特殊需求可以跳过
    httpProfile = HttpProfile()
    httpProfile.endpoint = "lighthouse.tencentcloudapi.com"

    # 实例化一个client选项，可选的，没有特殊需求可以跳过
    clientProfile = ClientProfile()
    clientProfile.httpProfile = httpProfile
    # 实例化要请求产品的client对象,clientProfile是可选的
    client = lighthouse_client.LighthouseClient(cred, "ap-beijing", clientProfile)

    # 实例化一个请求对象,每个接口都会对应一个request对象
    req = models.DescribeBlueprintsRequest()
    params = {

    }
    req.from_json_string(json.dumps(params))

    # 返回的resp是一个DescribeBlueprintsResponse的实例，与请求对象对应
    resp = client.DescribeBlueprints(req)
    # 输出json格式的字符串回包
    print(resp.to_json_string())
    with open("mirrors.json", "w", encoding="utf-8") as f:
        json.dump(json.loads(resp.to_json_string()), f, indent=2, ensure_ascii=False)
except TencentCloudSDKException as err:
    print(err)
